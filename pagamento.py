# PagamentoRepository  - acesso ao banco (tabela pagamento, disputa)
# PagamentoService     - regras: cobrança Pix (Asaas sandbox), retenção, disputa, estorno
# PagamentoController  - endpoints HTTP
#
# Um pagamento pertence a um CONTRATO. Estados:
#   pendente -> retido -> liberado          (liberado = feito pelo AulaRepository, ver abaixo)
#       |          |-> em_disputa -> liberado | reembolsado
#       |          |-> reembolsado
#       |-> cancelado
#
# "Retido" é só um status no nosso banco (escrow simulado). Quem LIBERA o pagamento
# no fluxo normal é o AulaRepository._liberar_pagamento, quando o aluno confirma com
# o PIN a última aula do contrato. Este módulo cuida de tudo o que vem antes (cobrar,
# confirmar o Pix) e dos desvios (disputa, estorno, decisão do admin).
import hmac
import os
import uuid
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, g, jsonify, request

from asaas_client import AsaasClient
from erros import ErroApi

COMISSAO_PERCENT = Decimal(os.getenv("COMISSAO_PERCENT", "20"))
CENTAVO = Decimal("0.01")

TRANSICOES = {
    "pendente": {"retido", "cancelado"},
    "retido": {"liberado", "reembolsado", "em_disputa"},
    "em_disputa": {"liberado", "reembolsado"},
    "liberado": set(),
    "reembolsado": set(),
    "cancelado": set(),
}

_BASE = """SELECT pg.*, c.id_usuario_aluno AS aluno_id, c.id_professor AS professor_id,
                  pr.id_usuario AS professor_usuario_id
           FROM pagamento pg
           JOIN contrato c          ON c.id_contrato   = pg.id_contrato
           JOIN perfil_professor pr ON pr.id_professor = c.id_professor"""


# ---------- REPOSITÓRIO ----------
class PagamentoRepository:
    def __init__(self, db):
        self.db = db

    def _consultar(self, sql, params=(), um=False):
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone() if um else cursor.fetchall()
        finally:
            conexao.close()

    def _executar(self, sql, params=()):
        """INSERT/UPDATE com commit. Devolve o nº de linhas afetadas."""
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(sql, params)
                linhas = cursor.rowcount
            conexao.commit()
            return linhas
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def buscar_contrato(self, id_contrato):
        return self._consultar(
            """SELECT id_contrato, id_usuario_aluno, id_professor, valor_total, status
               FROM contrato WHERE id_contrato = %s""", (id_contrato,), um=True)

    def buscar_usuario(self, id_usuario):
        return self._consultar("SELECT id_usuario, nome, email FROM usuario WHERE id_usuario = %s",
                               (id_usuario,), um=True)

    def buscar(self, id_pagamento):
        return self._consultar(_BASE + " WHERE pg.id_pagamento = %s", (id_pagamento,), um=True)

    def buscar_por_cobranca(self, id_cobranca):
        return self._consultar(_BASE + " WHERE pg.asaas_cobranca_id = %s", (id_cobranca,), um=True)

    def existe_ativo(self, id_contrato):
        return self._consultar(
            "SELECT 1 AS ok FROM pagamento WHERE id_contrato = %s "
            "AND status NOT IN ('cancelado', 'reembolsado')", (id_contrato,), um=True) is not None

    def aulas_realizadas(self, id_contrato):
        linha = self._consultar(
            "SELECT COUNT(*) AS n FROM aula WHERE id_contrato = %s AND status = 'realizada'",
            (id_contrato,), um=True)
        return linha["n"]

    def id_professor_do_usuario(self, id_usuario):
        linha = self._consultar("SELECT id_professor FROM perfil_professor WHERE id_usuario = %s",
                                (id_usuario,), um=True)
        return linha["id_professor"] if linha else None

    def saldo_professor(self, id_professor):
        return self._consultar(
            """SELECT
                 COALESCE(SUM(CASE WHEN pg.status = 'liberado' THEN pg.valor_professor END), 0) AS disponivel,
                 COALESCE(SUM(CASE WHEN pg.status IN ('retido', 'em_disputa') THEN pg.valor_professor END), 0) AS retido
               FROM pagamento pg JOIN contrato c ON c.id_contrato = pg.id_contrato
               WHERE c.id_professor = %s""", (id_professor,), um=True)

    def inserir(self, d):
        self._executar(
            """INSERT INTO pagamento (id_contrato, valor, comissao, valor_professor, metodo, status,
                   asaas_cobranca_id, pix_payload, pix_qrcode)
               VALUES (%s, %s, %s, %s, 'pix', 'pendente', %s, %s, %s)""",
            (d["id_contrato"], d["valor"], d["comissao"], d["valor_professor"],
             d["asaas_cobranca_id"], d["pix_payload"], d["pix_qrcode"]))
        return self._consultar("SELECT id_pagamento FROM pagamento WHERE asaas_cobranca_id = %s",
                               (d["asaas_cobranca_id"],), um=True)["id_pagamento"]

    def mudar_status(self, id_pagamento, de, para):
        """Compare-and-set atômico: só muda se o status atual for `de`."""
        extra = {"liberado": ", data_liberacao = NOW()", "retido": ", data_pagamento = NOW()"}
        return self._executar(
            f"UPDATE pagamento SET status = %s{extra.get(para, '')} "
            "WHERE id_pagamento = %s AND status = %s", (para, id_pagamento, de)) == 1

    def abrir_disputa(self, id_pagamento, id_usuario, motivo, descricao):
        self._executar(
            "INSERT INTO disputa (id_pagamento, id_usuario, motivo, descricao) VALUES (%s, %s, %s, %s)",
            (id_pagamento, id_usuario, motivo, descricao))

    def encerrar_disputas(self, id_pagamento, resultado):
        self._executar(
            "UPDATE disputa SET status = 'encerrada', resultado = %s "
            "WHERE id_pagamento = %s AND status <> 'encerrada'", (resultado, id_pagamento))

    def notificar(self, id_usuario, texto):
        self._executar("INSERT INTO notificacao (id_usuario, texto) VALUES (%s, %s)",
                       (id_usuario, texto[:255]))


# ---------- SERVIÇO ----------
class PagamentoService:
    def __init__(self, repositorio, gateway=None):
        self.repositorio = repositorio
        self.gateway = gateway or AsaasClient()

    # ---- criação ----
    def criar(self, id_aluno, id_contrato):
        contrato = self.repositorio.buscar_contrato(id_contrato)
        if not contrato:
            raise ErroApi("Contrato não encontrado", 404)
        if contrato["id_usuario_aluno"] != id_aluno:
            raise ErroApi("Este contrato não é seu", 403)
        if contrato["status"] != "ativo":
            raise ErroApi("O contrato não está ativo", 409)
        if self.repositorio.existe_ativo(id_contrato):
            raise ErroApi("Este contrato já possui um pagamento", 409)

        total = Decimal(str(contrato["valor_total"])).quantize(CENTAVO, ROUND_HALF_UP)
        comissao = (total * COMISSAO_PERCENT / 100).quantize(CENTAVO, ROUND_HALF_UP)

        aluno = self.repositorio.buscar_usuario(id_aluno) or {}
        # Sandbox: qualquer CPF válido serve (a tabela usuario não tem CPF).
        cliente = self.gateway.criar_cliente(
            aluno.get("nome", "Aluno"), aluno.get("email"),
            os.getenv("ASAAS_CPF_TESTE", "24971563792"))
        cobranca = self.gateway.criar_cobranca_pix(
            cliente["id"], total, f"Contrato Mentora #{id_contrato}", str(uuid.uuid4()))
        qr = self.gateway.qrcode_pix(cobranca["id"])

        id_pagamento = self.repositorio.inserir({
            "id_contrato": id_contrato, "valor": total, "comissao": comissao,
            "valor_professor": total - comissao, "asaas_cobranca_id": cobranca["id"],
            "pix_payload": qr.get("payload"), "pix_qrcode": qr.get("encodedImage")})
        return self.detalhar(id_pagamento, id_usuario=id_aluno)

    # ---- consulta ----
    def detalhar(self, id_pagamento, id_usuario=None, admin=False):
        p = self._carregar(id_pagamento)
        if not admin and id_usuario not in (p["aluno_id"], p["professor_usuario_id"]):
            raise ErroApi("Pagamento não encontrado", 404)
        return self._publico(p)

    def carteira(self, id_usuario):
        id_professor = self.repositorio.id_professor_do_usuario(id_usuario)
        if not id_professor:
            raise ErroApi("Apenas professores têm carteira", 403)
        s = self.repositorio.saldo_professor(id_professor)
        return {"disponivel": float(s["disponivel"]), "retido": float(s["retido"])}

    # ---- transições ----
    def confirmar_pagamento(self, id_cobranca):
        """Chamado pelo webhook do Asaas (ou pelo simulador). Idempotente."""
        p = self.repositorio.buscar_por_cobranca(id_cobranca)
        if p and self._pode(p["status"], "retido"):
            if self.repositorio.mudar_status(p["id_pagamento"], "pendente", "retido"):
                self.repositorio.notificar(
                    p["professor_usuario_id"], "Pagamento de um contrato confirmado. Pode dar as aulas!")

    def expirar(self, id_cobranca):
        p = self.repositorio.buscar_por_cobranca(id_cobranca)
        if p and self._pode(p["status"], "cancelado"):
            self.repositorio.mudar_status(p["id_pagamento"], "pendente", "cancelado")

    def simular_pagamento(self, id_aluno, id_pagamento):
        """Só sandbox: faz o papel do webhook sem precisar de URL pública."""
        p = self._carregar(id_pagamento)
        if p["aluno_id"] != id_aluno:
            raise ErroApi("Pagamento não encontrado", 404)
        self.confirmar_pagamento(p["asaas_cobranca_id"])
        return self.detalhar(id_pagamento, id_usuario=id_aluno)

    def liberar(self, id_pagamento):
        """Decisão do admin (ex.: resolver uma disputa a favor do professor)."""
        p = self._carregar(id_pagamento)
        if not self._pode(p["status"], "liberado"):
            raise ErroApi(f"Não é possível liberar um pagamento '{p['status']}'", 409)
        if not self.repositorio.mudar_status(id_pagamento, p["status"], "liberado"):
            raise ErroApi("O pagamento foi alterado por outra operação", 409)
        self.repositorio.encerrar_disputas(id_pagamento, "liberado ao professor")
        self.repositorio.notificar(p["professor_usuario_id"], "Pagamento liberado pelo administrador")
        return self._publico(self.repositorio.buscar(id_pagamento))

    def abrir_disputa(self, id_aluno, id_pagamento, motivo, descricao):
        p = self._carregar(id_pagamento)
        if p["aluno_id"] != id_aluno:
            raise ErroApi("Pagamento não encontrado", 404)
        if not self._pode(p["status"], "em_disputa"):
            raise ErroApi(f"Não é possível abrir disputa em pagamento '{p['status']}'", 409)
        if not self.repositorio.mudar_status(id_pagamento, "retido", "em_disputa"):
            raise ErroApi("O pagamento foi alterado por outra operação", 409)
        self.repositorio.abrir_disputa(
            id_pagamento, id_aluno, str(motivo or "Outro")[:100], str(descricao or ""))
        self.repositorio.notificar(p["professor_usuario_id"], "Um aluno abriu uma disputa de pagamento")
        return self._publico(self.repositorio.buscar(id_pagamento))

    def estornar(self, id_pagamento, id_usuario=None, admin=False):
        p = self._carregar(id_pagamento)
        if not admin:
            if p["aluno_id"] != id_usuario:
                raise ErroApi("Pagamento não encontrado", 404)
            if p["status"] == "em_disputa":
                raise ErroApi("Pagamento em disputa: aguarde a decisão do administrador", 409)
            if self.repositorio.aulas_realizadas(p["id_contrato"]) > 0:
                raise ErroApi("Já há aulas realizadas neste contrato. Abra uma disputa.", 409)

        if p["status"] == "pendente":
            novo, chamada = "cancelado", self.gateway.cancelar
        elif p["status"] in ("retido", "em_disputa"):
            novo, chamada = "reembolsado", self.gateway.estornar
        else:
            raise ErroApi(f"Não é possível estornar um pagamento '{p['status']}'", 409)

        antigo = p["status"]
        if not self.repositorio.mudar_status(id_pagamento, antigo, novo):
            raise ErroApi("O pagamento foi alterado por outra operação", 409)
        try:
            chamada(p["asaas_cobranca_id"])
        except ErroApi:
            self.repositorio.mudar_status(id_pagamento, novo, antigo)  # desfaz
            raise
        self.repositorio.encerrar_disputas(id_pagamento, "reembolsado ao aluno")
        return self._publico(self.repositorio.buscar(id_pagamento))

    # ---- internos ----
    def _carregar(self, id_pagamento):
        p = self.repositorio.buscar(id_pagamento)
        if not p:
            raise ErroApi("Pagamento não encontrado", 404)
        return p

    @staticmethod
    def _pode(de, para):
        return para in TRANSICOES.get(de, set())

    @staticmethod
    def _publico(p):
        return {
            "id": p["id_pagamento"], "id_contrato": p["id_contrato"], "status": p["status"],
            "valor": float(p["valor"]), "comissao": float(p["comissao"]),
            "valor_professor": float(p["valor_professor"]),
            "pix_copia_e_cola": p["pix_payload"], "pix_qrcode_base64": p["pix_qrcode"],
        }


# ---------- CONTROLLER ----------
class PagamentoController:
    def __init__(self, service, autenticacao):
        self.service = service
        self.bp = Blueprint("pagamentos", __name__)
        login, admin = autenticacao.requer_login, autenticacao.requer_admin
        regra = self.bp.add_url_rule

        # aluno / professor (exigem login)
        regra("/api/contratos/<int:id_contrato>/pagamento", view_func=login(self.criar),
              methods=["POST"])
        regra("/api/pagamentos/<int:id_pagamento>", view_func=login(self.detalhar),
              methods=["GET"])
        regra("/api/pagamentos/<int:id_pagamento>/estornar", view_func=login(self.estornar),
              methods=["POST"])
        regra("/api/pagamentos/<int:id_pagamento>/disputa", view_func=login(self.disputa),
              methods=["POST"])
        regra("/api/pagamentos/<int:id_pagamento>/simular-pagamento",
              view_func=login(self.simular), methods=["POST"])
        regra("/api/carteira", view_func=login(self.carteira), methods=["GET"])

        # admin
        regra("/api/admin/pagamentos/<int:id_pagamento>", view_func=admin(self.detalhar_admin),
              methods=["GET"])
        regra("/api/admin/pagamentos/<int:id_pagamento>/liberar",
              view_func=admin(self.liberar_admin), methods=["POST"])
        regra("/api/admin/pagamentos/<int:id_pagamento>/estornar",
              view_func=admin(self.estornar_admin), methods=["POST"])

        # chamado pelo Asaas (sem login; protegido por token)
        regra("/api/pagamentos/webhook/asaas", view_func=self.webhook, methods=["POST"])

    def criar(self, id_contrato):
        return jsonify(self.service.criar(g.id_usuario, id_contrato)), 201

    def detalhar(self, id_pagamento):
        return jsonify(self.service.detalhar(id_pagamento, id_usuario=g.id_usuario)), 200

    def estornar(self, id_pagamento):
        return jsonify(self.service.estornar(id_pagamento, id_usuario=g.id_usuario)), 200

    def disputa(self, id_pagamento):
        dados = request.get_json(silent=True) or {}
        return jsonify(self.service.abrir_disputa(
            g.id_usuario, id_pagamento, dados.get("motivo"), dados.get("descricao"))), 200

    def carteira(self):
        return jsonify(self.service.carteira(g.id_usuario)), 200

    def simular(self, id_pagamento):
        if "sandbox" not in os.getenv("ASAAS_URL", "sandbox"):
            raise ErroApi("Disponível apenas no sandbox", 403)
        return jsonify(self.service.simular_pagamento(g.id_usuario, id_pagamento)), 200

    def detalhar_admin(self, id_pagamento):
        return jsonify(self.service.detalhar(id_pagamento, admin=True)), 200

    def liberar_admin(self, id_pagamento):
        return jsonify(self.service.liberar(id_pagamento)), 200

    def estornar_admin(self, id_pagamento):
        return jsonify(self.service.estornar(id_pagamento, admin=True)), 200

    def webhook(self):
        esperado = os.getenv("ASAAS_WEBHOOK_TOKEN", "")
        recebido = request.headers.get("asaas-access-token", "")
        if not esperado or not hmac.compare_digest(esperado, recebido):
            raise ErroApi("Token inválido", 401)
        dados = request.get_json(silent=True) or {}
        id_cobranca = (dados.get("payment") or {}).get("id")
        evento = dados.get("event")
        if id_cobranca:
            if evento in ("PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"):
                self.service.confirmar_pagamento(id_cobranca)
            elif evento in ("PAYMENT_OVERDUE", "PAYMENT_DELETED"):
                self.service.expirar(id_cobranca)
        return jsonify(ok=True), 200  # sempre 200 para o Asaas não pausar a fila
