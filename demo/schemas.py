# schemas.py
from pydantic import BaseModel
from typing import Dict, List, Union, Optional

class SubmitPayload(BaseModel):
    person_key: str
    selected: Dict[str, Union[str, List[str]]] = {}
    texts: Dict[str, str] = {}

class ResponseOut(BaseModel):
    id: int
    person_key: str
    selected: Dict[str, Union[str, List[str]]]
    texts: Dict[str, str]
    image_path: Optional[str]

    class Config:
        from_attributes = True  # ← ここを修正（Pydantic v2対応）
