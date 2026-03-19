import os
from decimal import Decimal
from typing import Union

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, exists, select, update, or_
from sqlalchemy.orm import Session
import asyncio
from google.oauth2 import id_token
from google.auth.transport import requests

from contextlib import asynccontextmanager
from database import SessionLocal
import DB_models
from models import GroupMessage, Message
from database import engine, get_db

WEBCLIENT_ID = os.getenv("WEBCLIENT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    async with engine.begin() as conn:
        # This safely runs the synchronous table creation inside the async engine
        await conn.run_sync(DB_models.Base.metadata.create_all)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    # Everything before the 'yield' runs exactly once when the server boots up.
    print("Booting up: Ensuring database tables exist...")
    await init_db()

    yield  # The server pauses here and handles all user requests/websockets
    # --- SHUTDOWN LOGIC ---
    print("Shutting down gracefully...")
app = FastAPI(lifespan=lifespan)


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket_: WebSocket, UserId: int):
        await websocket_.accept()
        self.active_connections[UserId] = websocket_

    async def disconnect(self, UserId: int):
        del self.active_connections[UserId]

    async def send_message(self, message: Message, ToId: int):
        if ToId in self.active_connections:
            await self.active_connections[ToId].send_json(message)

manager = ConnectionManager()

@app.post("/login")
async def login(token: str, db: Session = Depends(get_db)):
    try:
        IdInfo = id_token.verify_oauth2_token(token, requests.Request(), WEBCLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid token")

    try:
        user = await db.execute(
                        select(DB_models.OAuthTable.UserId)
                        .where(DB_models.OAuthTable.OAuthId==IdInfo["sub"])
                    ).scalar()
    
        if not user:
            user_ = DB_models.User(
                Name=IdInfo["name"],
                Email=IdInfo["email"],
                ProfilePictureUrl=IdInfo.get("picture")
            )

            db.add(user_)
            await db.flush()
            await db.refresh(user_)

            outh_ = DB_models.OAuth(
                UserId=user_.Id,
                OAuthId=IdInfo["sub"]
            )

            db.add(outh_)
            await db.commit()
            
            return {"UserId": user_.Id}

        return {"UserId": user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/ws/{UserId}/get_all_messages")
async def get_all_messages(UserId: int, db: Session = Depends(get_db)):
    try:
        Messages = await db.execute(
            select(DB_models.Message)
            .where(or_(DB_models.Message.FromId==UserId, DB_models.Message.ToId==UserId))
        ).scalars().all()

        Groups = await db.execute(
            select(DB_models.MapTable.GroupId)
            .where(DB_models.MapTable.UserId == UserId)
        ).scalars().all()

        GroupMessages = await db.execute(
            select(DB_models.GroupMessage)
            .where(DB_models.GroupMessage.GroupId.in_(Groups))
        ).scalars().all()

        return [Messages, GroupMessages]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/change_username")
async def change_username(UserId: int, NewUsername: str, db: Session = Depends(get_db)):
    try:
        await db.execute(
            update(DB_models.User)
            .where(DB_models.User.Id == UserId)
            .values(Username=NewUsername)
        )
        await db.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws/{Username}")
async def websocket_endpoint(websocket_: WebSocket, Username: str):
    UserId: 0
    async with SessionLocal() as db:
        UserId = await db.execute(
            select(DB_models.User.Id)
            .where(DB_models.User.Username == Username)
        ).scalar()

    if not UserId:
        websocket_.close(code=1008)

    await manager.connect(websocket_, UserId)

    try:
        while True:
            message = await websocket_.receive_json()

            AllUsers = []
            async with SessionLocal() as db:
                if message["Type"]==0:
                    Message = DB_models.Message(
                        FromId=message["FromId"],
                        ToId=message["ToId"],
                        Message=message["Message"],
                        SentAt=message["SentAt"]
                    )
                    db.add(Message)
                    await db.commit()
                elif message["Type"]==1:
                    Group = await db.execute(
                        select(DB_models.MapTable.UserId)
                        .where(DB_models.MapTable.GroupId == message["ToId"])
                    ).scalars().all()

                    GroupMessage = DB_models.Message(
                        FromId=message["FromId"],
                        ToId=message["ToId"],
                        Message=message["Message"],
                        SentAt=message["SentAt"]
                    )
                    db.add(GroupMessage)
                    await db.commit()
                elif message["Type"]==2:
                    rows = await db.execute(
                        select(DB_models.User.Username, DB_models.User.UserId)
                    )
                    AllUsers = [{"Username": row.Username, "Id": row.Id} for row in rows.all()]             

            if message["Type"]==0:
                await manager.send_message(message, message["ToId"])
            elif message["Type"]==1:
                Tasks = [manager.send_message(message, To_) for To_ in Group]
                await asyncio.gather(*Tasks)
            elif message["Type"]==2:
                await manager.send_message(AllUsers, message["UserId"])

    except WebSocketDisconnect:
        await manager.disconnect(websocket_, UserId)

'''
Left:
- Receive time updation
- Message deletion
- Group creation & deletion

For frontend: username change = websocket re-establish.
'''