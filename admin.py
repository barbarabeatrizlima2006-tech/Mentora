# AdminRepository / AdminService / AdminController  (só para usuários com tipo = 'admin')
import re

import pymysql
from flask import Blueprint, jsonify, request, send_from_directory

from base import RepositorioBase
from erros import ErroApi

STATUS_VALIDOS = ("pendente", "ativo", "recusado", "inativo")
NOME_COMPROVANTE = re.compile(r"^[0-9a-f]{32}\.(jpg|png|pdf)$")


class AdminRepository(RepositorioBase):
    def listar(self, status):
        sql = """SELECT p.id_professor, u.nome, u.email, p.formacao, p.descricao, p.status,
                        p.comprovante IS NOT NULL AS tem_comprovante
                 FROM perfil_professor p JOIN usuario u ON u.id_usuario = p.id_usuario"""
        params = ()
        if status:
            sql += " WHERE p.status = %s"
            params = (status,)
        return self._consultar(sql + " ORDER BY p.id_professor", params)

    def comprovante(self, id_professor):
        linha = self._consultar(
            "SELECT comprovante FROM perfil_professor WHERE id_professor = %s",
            (id_professor,), um=True)
        return linha["comprovante"] if linha else None

    def alterar_status(self, id_professor, novo, texto):
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cur:
                cur.execute("SELECT id_usuario FROM perfil_professor WHERE id_professor = %s FOR UPDATE",
                            (id_professor,))
                professor = cur.fetchone()
                if not professor:
                    return False
                cur.execute("UPDATE perfil_professor SET status = %s WHERE id_professor = %s",
                            (novo, id_professor))
                cur.execute("INSERT INTO notificacao (id_usuario, texto) VALUES (%s, %s)",
                            (professor["id_usuario"], texto))
            conexao.commit()
            return True
        except pymysql.MySQLError:
            conexao.rollback()
            raise
        finally:
            conexao.close()


class AdminService:
    AVISOS = {
        "ativo": "Seu perfil foi aprovado! Você já aparece nas buscas dos alunos.",
        "recusado": "Seu perfil não foi aprovado. Revise seus dados e documentos.",
        "inativo": "Seu perfil foi desativado.",
        "pendente": "Seu perfil voltou para análise.",
    }

    def __init__(self, repositorio):
        self.repositorio = repositorio

    def listar(self, status):
        if status and status not in STATUS_VALIDOS:
            raise ErroApi("status inválido", 400)
        return [{
            "id": p["id_professor"], "nome": p["nome"], "email": p["email"],
            "formacao": p["formacao"], "descricao": p["descricao"], "status": p["status"],
            "tem_comprovante": bool(p["tem_comprovante"]),
        } for p in self.repositorio.listar(status)]

    def alterar_status(self, id_professor, dados):
        novo = (dados.get("status") or "").strip()
        if novo not in STATUS_VALIDOS:
            raise ErroApi("status deve ser: " + ", ".join(STATUS_VALIDOS), 400)
        if not self.repositorio.alterar_status(id_professor, novo, self.AVISOS[novo]):
            raise ErroApi("Professor não encontrado", 404)
        return {"id": id_professor, "status": novo}

    def nome_do_comprovante(self, id_professor):
        nome = self.repositorio.comprovante(id_professor)
        if not nome or not NOME_COMPROVANTE.match(nome):
            raise ErroApi("Comprovante não encontrado", 404)
        return nome


class AdminController:
    def __init__(self, service, autenticacao, arquivos):
        self.service = service
        self.arquivos = arquivos
        self.bp = Blueprint("admin", __name__)
        so_admin = autenticacao.requer_admin
        self.bp.add_url_rule("/api/admin/professores", view_func=so_admin(self.listar), methods=["GET"])
        self.bp.add_url_rule("/api/admin/professores/<int:id_professor>",
                             view_func=so_admin(self.alterar), methods=["PATCH"])
        self.bp.add_url_rule("/api/admin/professores/<int:id_professor>/comprovante",
                             view_func=so_admin(self.comprovante), methods=["GET"])

    def listar(self):
        return jsonify(self.service.listar(request.args.get("status"))), 200

    def alterar(self, id_professor):
        dados = request.get_json(silent=True) or {}
        return jsonify(self.service.alterar_status(id_professor, dados)), 200

    def comprovante(self, id_professor):
        nome = self.service.nome_do_comprovante(id_professor)
        return send_from_directory(self.arquivos.pasta("comprovantes"), nome)
