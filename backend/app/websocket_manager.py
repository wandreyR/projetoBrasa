import asyncio
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger("brasa.websocket")

# Tempo máximo para entregar uma mensagem a um cliente. Uma aba da cozinha
# travada (rede ruim, notebook suspenso) não pode segurar o envio para as outras.
TIMEOUT_ENVIO_SEGUNDOS = 5.0


class ConnectionManager:
    """Mantém as conexões WebSocket ativas da tela da cozinha e envia
    notificações quando um pedido é criado ou muda de status."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    @property
    def total_conexoes(self) -> int:
        return len(self.active_connections)

    async def connect(self, websocket: WebSocket):
        """Registra uma conexão já aceita (o accept é feito na rota, após autenticar)."""
        self.active_connections.add(websocket)
        logger.info("Cozinha conectada (%d ativa(s))", self.total_conexoes)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info("Cozinha desconectada (%d ativa(s))", self.total_conexoes)

    async def _enviar(self, websocket: WebSocket, message: dict) -> bool:
        try:
            await asyncio.wait_for(websocket.send_json(message), TIMEOUT_ENVIO_SEGUNDOS)
            return True
        except Exception as exc:  # conexão fechada, timeout, erro de rede...
            logger.warning("Falha ao enviar para a cozinha, removendo conexão: %s", exc)
            return False

    async def broadcast(self, message: dict):
        """Envia para todas as conexões em paralelo e descarta as que falharem.

        Nunca levanta exceção: quem chama (ex.: criação de pedido) já gravou no
        banco e não deve devolver erro ao cliente por causa de uma aba da cozinha.
        """
        # snapshot: o conjunto pode mudar enquanto aguardamos os envios
        conexoes = list(self.active_connections)
        if not conexoes:
            return

        resultados = await asyncio.gather(
            *(self._enviar(ws, message) for ws in conexoes), return_exceptions=True
        )
        for ws, ok in zip(conexoes, resultados):
            if ok is not True:
                self.disconnect(ws)


manager = ConnectionManager()
