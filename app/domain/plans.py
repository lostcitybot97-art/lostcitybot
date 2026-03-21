# app/domain/plans.py

PLANS = {
    "semanal": {
        "title": "Plano semanal",
        "price": 1.99,
        "days": 4,
        "renewal_discount_percent": 10,
    },
    "mensal": {
        "title": "Plano mensal",
        "price": 26.90,
        "days": 30,
        "renewal_discount_percent": 10,
    },
}


def get_plan(plan_id: str) -> dict | None:
    return PLANS.get(plan_id)


def plan_exists(plan_id: str) -> bool:
    return plan_id in PLANS
