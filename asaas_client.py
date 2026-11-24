"""Cliente mínimo da API do Asaas (sandbox por padrão)."""
import os
from datetime import date, timedelta

import requests

from erros import ErroApi


class AsaasClient:
    def __init__(self):
        self.base = os.getenv("ASAAS_URL", "https://api-sandbox.asaas.com/v3")
        self.chave = os.getenv("ASAAS_API_KEY")

    def _req(self, metodo, caminho, corpo=None):
        if not self.chave:
            raise ErroApi("ASAAS_API_KEY não configurada no .env.", 500)
        try:
            r = requests.request(
                metodo, f"{self.base}{caminho}", json=corpo, timeout=15,
                headers={"access_token": self.chave, "User-Agent": "Mentora",
                         "Content-Type": "application/json"})
        except requests.RequestException:
            raise ErroApi("Não foi possível falar com o gateway de pagamento.", 502)
        if r.status_code >= 400:
            try:
                msg = r.json()["errors"][0]["description"]
            except Exception:
                msg = "Erro no gateway de pagamento."
            raise ErroApi(msg, 502)
        return r.json()

    def criar_cliente(self, nome, email, cpf):
        return self._req("POST", "/customers",
                         {"name": nome, "email": email, "cpfCnpj": cpf})

    def criar_cobranca_pix(self, cliente_id, valor, descricao, referencia):
        vencimento = (date.today() + timedelta(days=1)).isoformat()
        return self._req("POST", "/payments", {
            "customer": cliente_id, "billingType": "PIX", "value": float(valor),
            "dueDate": vencimento, "description": descricao,
            "externalReference": referencia})

    def qrcode_pix(self, cobranca_id):
        """Retorna {encodedImage (base64), payload (copia e cola), expirationDate}."""
        return self._req("GET", f"/payments/{cobranca_id}/pixQrCode")

    def estornar(self, cobranca_id):
        return self._req("POST", f"/payments/{cobranca_id}/refund")

    def cancelar(self, cobranca_id):
        return self._req("DELETE", f"/payments/{cobranca_id}")
