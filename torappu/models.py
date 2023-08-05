from pydantic import BaseModel


class Version(BaseModel):
    res_version: str
    client_version: str


class Config(BaseModel):
    token: str
    endpoint: str
