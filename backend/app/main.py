import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine
from .routers import auth, decisions, imports, mappings, market, products, quotes, recipes

app = FastAPI(title="农产品报价归集与可比成本分析平台", version="1.1.0",
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, products.router, imports.router, quotes.router,
          mappings.router, decisions.router, market.router, recipes.router):
    app.include_router(r)


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    if os.getenv("SEED_ON_START", "false").lower() == "true":
        from .seed import seed_if_empty
        from .seed_recipe import seed_recipe_domain
        from .database import SessionLocal
        db = SessionLocal()
        try:
            seed_if_empty(db)
            seed_recipe_domain(db)
        finally:
            db.close()


@app.get("/api/health")
def health():
    return {"status": "ok"}
