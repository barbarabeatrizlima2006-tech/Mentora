# Usuario            - modelo (tabela)
# UsuarioRepository  - acesso ao banco (salvar, buscar, atualizar)
# UsuarioService     - regras de negócio
# UsuarioController  - endpoints HTTP

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pymysql
from flask import Blueprint, g, jsonify, request

from erros import ErroApi
from seguranca import Senha

EMAIL_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ------- MODELO: os dados de um usuario --------
@dataclass
class Usuario:
    nome: str
    email: str
    senha_hash: str
    telefone: Optional[str] = None
    data_nascimento: Optional[str] = None
    id: Optional[int] = None

    def para_dict(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "telefone": self.telefone,
            "data_nascimento": self.data_nascimento,
        }


# --------- REPOSITÓRIO: conversa com o banco MySQL -------------------
class UsuarioRepository:
    def __init__(self, db):
        self.db = db

    def inserir(self, usuario):
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO usuario (nome, email, senha, telefone, data_nascimento)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (usuario.nome, usuario.email, usuario.senha_hash,
                     usuario.telefone, usuario.data_nascimento),
                )
                novo_id = cursor.lastrowid
            conexao.commit()
            return novo_id
        except pymysql.err.IntegrityError as e:
            conexao.rollback()
            if e.args[0] == 1062:  # entrada duplicada (UNIQUE do email)
                raise ErroApi("E-mail já cadastrado", 409)
            raise
        except pymysql.MySQLError:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def buscar_por_email(self, email):
        # usado no login (traz o hash da senha)
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(
                    "SELECT id_usuario, nome, email, senha, tipo FROM usuario WHERE email = %s",
                    (email,),
                )
                return cursor.fetchone()
        finally:
            conexao.close()

    def buscar_por_id(self, id_usuario):
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id_usuario, nome, email, telefone, data_nascimento, foto, tipo
                    FROM usuario WHERE id_usuario = %s
                    """,
                    (id_usuario,),
                )
                return cursor.fetchone()
        finally:
            conexao.close()

    def atualizar(self, id_usuario, nome, email, telefone, data_nascimento):
        conexao = self.db.conectar()
        try:
            with conexao.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE usuario
                    SET nome = %s, email = %s, telefone = %s, data_nascimento = %s
                    WHERE id_usuario = %s
                    """,
                    (nome, email, telefone, data_nascimento, id_usuario),
                )
            conexao.commit()
        except pymysql.err.IntegrityError as e:
            conexao.rollback()
            if e.args[0] == 1062:
                raise ErroApi("E-mail já cadastrado", 409)
            raise
        except pymysql.MySQLError:
            conexao.rollback()
            raise
        finally:
            conexao.close()


# ---------- SERVIÇO: regras de negócio ----------
class UsuarioService:
    SENHA_MIN = 8

    def __init__(self, repositorio, token):
        self.repositorio = repositorio
        self.token = token

    # --- validações pequenas, reaproveitadas ---
    @staticmethod
    def _validar_email(email):
        if not EMAIL_VALIDO.match(email) or len(email) > 150:
            raise ErroApi("E-mail inválido", 400)

    @staticmethod
    def _validar_data(texto):
        if texto in (None, ""):
            return None
        try:
            datetime.strptime(texto, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ErroApi("data_nascimento deve estar no formato AAAA-MM-DD", 400)
        return texto

    @staticmethod
    def _perfil_para_dict(linha):
        data = linha["data_nascimento"]
        return {
            "id": linha["id_usuario"],
            "nome": linha["nome"],
            "email": linha["email"],
            "telefone": linha["telefone"],
            "data_nascimento": data.isoformat() if data else None,
            "foto": linha["foto"],
            "tipo": linha["tipo"],
        }

    # --- casos de uso ---
    def cadastrar(self, dados):
        nome = (dados.get("nome") or "").strip()
        email = (dados.get("email") or "").strip().lower()
        senha = dados.get("senha") or ""

        if not nome or not email or not senha:
            raise ErroApi("nome, email e senha são obrigatórios", 400)
        if len(nome) > 100:
            raise ErroApi("O nome deve ter no máximo 100 caracteres", 400)
        self._validar_email(email)
        if len(senha) < self.SENHA_MIN:
            raise ErroApi(f"A senha deve ter pelo menos {self.SENHA_MIN} caracteres", 400)
        if not Senha.tamanho_valido(senha):
            raise ErroApi("A senha deve ter no máximo 72 bytes", 400)

        usuario = Usuario(
            nome=nome,
            email=email,
            senha_hash=Senha.gerar_hash(senha),
            telefone=dados.get("telefone"),
            data_nascimento=self._validar_data(dados.get("data_nascimento")),
        )
        usuario.id = self.repositorio.inserir(usuario)
        # já devolve o token: quem acabou de criar a conta entra logado
        return usuario, self.token.gerar(usuario.id, "comum")

    def login(self, dados):
        email = (dados.get("email") or "").strip().lower()
        senha = dados.get("senha") or ""
        if not email or not senha:
            raise ErroApi("email e senha são obrigatórios", 400)

        registro = self.repositorio.buscar_por_email(email)
        hash_salvo = registro["senha"] if registro else Senha.HASH_FALSO
        senha_ok = Senha.verificar(senha, hash_salvo)

        # mesma mensagem para "e-mail não existe" e "senha errada"
        if not registro or not senha_ok:
            raise ErroApi("E-mail ou senha inválidos", 401)

        token = self.token.gerar(registro["id_usuario"], registro["tipo"])
        usuario = {"id": registro["id_usuario"], "nome": registro["nome"],
                   "email": registro["email"], "tipo": registro["tipo"]}
        return usuario, token

    def obter_perfil(self, id_usuario):
        linha = self.repositorio.buscar_por_id(id_usuario)
        if not linha:
            raise ErroApi("Usuário não encontrado", 404)
        return self._perfil_para_dict(linha)

    def atualizar_perfil(self, id_usuario, dados):
        atual = self.repositorio.buscar_por_id(id_usuario)
        if not atual:
            raise ErroApi("Usuário não encontrado", 404)

        nome = (dados.get("nome", atual["nome"]) or "").strip()
        email = (dados.get("email", atual["email"]) or "").strip().lower()
        telefone = dados.get("telefone", atual["telefone"])
        nascimento = dados.get(
            "data_nascimento",
            atual["data_nascimento"].isoformat() if atual["data_nascimento"] else None,
        )

        if not nome or not email:
            raise ErroApi("nome e email não podem ficar vazios", 400)
        if len(nome) > 100:
            raise ErroApi("O nome deve ter no máximo 100 caracteres", 400)
        self._validar_email(email)

        self.repositorio.atualizar(id_usuario, nome, email, telefone,
                                   self._validar_data(nascimento))
        return self.obter_perfil(id_usuario)


# ---------- CONTROLLER: recebe a requisição HTTP e devolve a resposta ----------
class UsuarioController:
    def __init__(self, service, autenticacao):
        self.service = service
        self.bp = Blueprint("usuarios", __name__)
        self.bp.add_url_rule("/api/usuarios", view_func=self.cadastrar, methods=["POST"])
        self.bp.add_url_rule("/api/login", view_func=self.login, methods=["POST"])
        self.bp.add_url_rule("/api/me", view_func=autenticacao.requer_login(self.ver_perfil),
                             methods=["GET"])
        self.bp.add_url_rule("/api/me", view_func=autenticacao.requer_login(self.editar_perfil),
                             methods=["PUT"])

    def cadastrar(self):
        dados = request.get_json(silent=True) or {}
        usuario, token = self.service.cadastrar(dados)
        return jsonify({"mensagem": "Usuário criado", "usuario": usuario.para_dict(),
                        "token": token}), 201

    def login(self):
        dados = request.get_json(silent=True) or {}
        usuario, token = self.service.login(dados)
        return jsonify({"usuario": usuario, "token": token}), 200

    def ver_perfil(self):
        return jsonify(self.service.obter_perfil(g.id_usuario)), 200

    def editar_perfil(self):
        dados = request.get_json(silent=True) or {}
        return jsonify(self.service.atualizar_perfil(g.id_usuario, dados)), 200