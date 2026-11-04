# Segurança: senha (bcrypt), token (JWT) e proteção de rotas
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import g, request

from erros import ErroApi


class Senha:
    ROUNDS = 12
    MAX_BYTES = 72  # Limite do bcrypt
    # Hash "de mentira", usado no login quando o e-mail não existe.
    # Assim a resposta demora o mesmo tempo e não revela se o e-mail está cadastrado.
    HASH_FALSO = bcrypt.hashpw(b"senha-falsa", bcrypt.gensalt(rounds=ROUNDS)).decode("utf-8")

    @classmethod
    def tamanho_valido(cls, senha):
        return len(senha.encode("utf-8")) <= cls.MAX_BYTES

    @classmethod
    def gerar_hash(cls, senha):
        return bcrypt.hashpw(
            senha.encode("utf-8"),
            bcrypt.gensalt(rounds=cls.ROUNDS),
        ).decode("utf-8")

    @staticmethod
    def verificar(senha, hash_salvo):
        try:
            return bcrypt.checkpw(senha.encode("utf-8"), hash_salvo.encode("utf-8"))
        except ValueError:  # hash inválido (ex.: os hashes fictícios do SQL de exemplo)
            return False


class Token:
    # Cria e valida o JWT. O segredo vem do .env (JWT_SECRET).
    ALGORITMO = "HS256"

    def __init__(self, horas_validade=8):
        self.segredo = os.getenv("JWT_SECRET")
        if not self.segredo or len(self.segredo) < 32:
            raise RuntimeError("Defina JWT_SECRET no .env com pelo menos 32 caracteres.")
        self.validade = timedelta(hours=horas_validade)

    def gerar(self, id_usuario, tipo="comum"):
        agora = datetime.now(timezone.utc)
        payload = {
            "sub": str(id_usuario),  # o JWT exige que "sub" seja texto
            "tipo": tipo,
            "iat": agora,
            "exp": agora + self.validade,
        }
        return jwt.encode(payload, self.segredo, algorithm=self.ALGORITMO)

    def validar(self, token):
        try:
            return jwt.decode(token, self.segredo, algorithms=[self.ALGORITMO])
        except jwt.ExpiredSignatureError:
            raise ErroApi("Sessão expirada. Entre novamente.", 401)
        except jwt.InvalidTokenError:
            raise ErroApi("Token inválido.", 401)


class Autenticacao:
    # Protege rotas. Uso:  view_func=autenticacao.requer_login(self.minha_rota)
    # Dentro da rota, g.id_usuario e g.tipo ficam disponíveis.
    def __init__(self, token):
        self.token = token

    def _ler_cabecalho(self):
        partes = request.headers.get("Authorization", "").split()
        if len(partes) != 2 or partes[0].lower() != "bearer":
            raise ErroApi("Faça login para continuar.", 401)
        return self.token.validar(partes[1])

    def requer_login(self, funcao):
        @wraps(funcao)
        def protegida(*args, **kwargs):
            dados = self._ler_cabecalho()
            g.id_usuario = int(dados["sub"])
            g.tipo = dados.get("tipo", "comum")
            return funcao(*args, **kwargs)
        return protegida

    def requer_admin(self, funcao):
        @wraps(funcao)
        def so_admin(*args, **kwargs):
            if g.tipo != "admin":
                raise ErroApi("Acesso restrito a administradores.", 403)
            return funcao(*args, **kwargs)
        return self.requer_login(so_admin)