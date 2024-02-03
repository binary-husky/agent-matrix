import os
import sys
import time
import uuid
import json
import platform
import pickle
import asyncio
import threading
import subprocess
from loguru import logger
from queue import Queue
from fastapi import FastAPI, WebSocket
from agent_matrix.agent.agent_proxy import AgentProxy
from agent_matrix.msg.general_msg import GeneralMsg
from agent_matrix.matrix.matrix_userinterface_bridge import UserInterfaceBridge
from typing import List


class MasterMindWebSocketServer(UserInterfaceBridge):

    def __init__(self) -> None:
        self.websocket_connections = {}
        pass

    async def maintain_agent_connection_forever(self, agent_id: str, websocket: WebSocket, client_id: str):
        async def wait_message_to_send(message_queue_out: asyncio.Queue, agent_proxy: AgentProxy):
            # 🚀 proxy agent -> matrix -> real agent
            msg_cnt = 0
            while True:
                # 🕜 wait message from the proxy agent
                msg: GeneralMsg = await message_queue_out.get()
                msg_cnt += 1
                logger.info('sending agent:', agent_id, '\tcnt:', msg_cnt, '\tcommand:', msg.command)
                if msg.dst == 'matrix':
                    raise NotImplementedError()
                else:
                    # send the message to the real agent
                    await websocket.send_bytes(pickle.dumps(msg))

        async def receive_forever(message_queue_in: asyncio.Queue, agent_proxy: AgentProxy):
            # 🚀 real agent -> matrix -> proxy agent
            # 🚀 real agent -> matrix
            msg_cnt = 0
            while True:
                # 🕜 wait websocket message from the real agent
                msg: GeneralMsg = pickle.loads(await websocket.receive_bytes())
                msg_cnt += 1
                logger.info('receiving agent:', agent_id, '\tcnt:', msg_cnt, '\tcommand:', msg.command)
                if msg.dst == 'matrix':
                    raise NotImplementedError()
                else:
                    # deliver the message to the proxy agent
                    await message_queue_in.put(msg)

        message_queue_out, message_queue_in, agent_proxy = self.make_queue(agent_id, websocket, client_id)
        t_x = asyncio.create_task(wait_message_to_send(message_queue_out, agent_proxy))
        t_r = asyncio.create_task(receive_forever(message_queue_in, agent_proxy))
        await t_x
        await t_r

    def make_queue(self, agent_id, websocket, client_id):
        message_queue_out = asyncio.Queue()
        message_queue_in = asyncio.Queue()
        assert agent_id in self.websocket_connections, f"agent_id {agent_id} not found in self.websocket_connections"
        agent_proxy: AgentProxy = self.websocket_connections[agent_id]
        agent_proxy.update_connection_info(
            websocket=websocket,
            client_id=client_id,
            message_queue_out=message_queue_out,
            message_queue_in=message_queue_in
        )
        return message_queue_out, message_queue_in, agent_proxy

    async def long_task_01_wait_incoming_connection(self):
        # task 1 wait incoming agent connection
        logger.info("task 1 wait incoming agent connection")

        async def launch_websocket_server():
            app = FastAPI()

            @app.websocket("/ws_agent")
            async def _register_incoming_agents(websocket: WebSocket):
                await websocket.accept()
                msg: GeneralMsg = pickle.loads(await websocket.receive_bytes())
                if msg.dst != "matrix" or msg.command != "connect_to_matrix":
                    raise ValueError()
                agent_id = msg.kwargs['agent_id']
                if agent_id in self.websocket_connections:
                    logger.warning(f"agent_id {agent_id}, connection established")
                    client_id = uuid.uuid4().hex
                    await self.maintain_agent_connection_forever(agent_id, websocket, client_id)
                else:
                    logger.warning(f"agent_id {agent_id} un-known, connection aborted")
                    await websocket.close()

            logger.info("uvicorn starts")
            import uvicorn
            config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()

        await launch_websocket_server()
        logger.info("uvicorn terminated")