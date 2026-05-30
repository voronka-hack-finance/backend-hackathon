from pydantic import BaseModel, Field


class Pagination(BaseModel):
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=500)
    total: int = Field(ge=0)


class Page(BaseModel):
    items: list
    pagination: Pagination
