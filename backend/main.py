from decimal import Decimal
from typing import Union

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

import DB_models
import models
from database import engine, get_db

DB_models.Base.metadata.create_all(bind=engine)
app = FastAPI()