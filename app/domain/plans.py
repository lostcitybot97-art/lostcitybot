# app/domain/plans.py

PLANS = {
    "semanal": {
        "title": "Plano Semanal",
        "price": 1.99,  # valor de teste
        "days": 7,
    },
    "mensal": {
        "title": "Plano Mensal",
        "price": 1.99,  # valor de teste
        "days": 30,
    },
}


def get_plan(plan_id: str) -> dict | None:
    return PLANS.get(plan_id)


def plan_exists(plan_id: str) -> bool:
    return plan_id in PLANS
