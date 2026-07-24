from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient


async def create_weight(
    client: AsyncClient,
    *,
    recorded_on: str,
    weight_kg: str,
    body_fat_percent: str | None = None,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/health/weights",
        json={
            "recorded_on": recorded_on,
            "weight_kg": weight_kg,
            "body_fat_percent": body_fat_percent,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_nutrition(
    client: AsyncClient,
    *,
    recorded_on: str,
    calories: int,
    calorie_target: int | None = 2200,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/health/nutrition",
        json={
            "recorded_on": recorded_on,
            "calories": calories,
            "calorie_target": calorie_target,
            "protein_grams": "150.00",
            "carbs_grams": "220.00",
            "fat_grams": "70.00",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_weight_crud_filters_and_pagination(api_client: AsyncClient) -> None:
    first = await create_weight(
        api_client,
        recorded_on="2026-07-20",
        weight_kg="82.40",
        body_fat_percent="18.50",
    )
    middle = await create_weight(
        api_client,
        recorded_on="2026-07-22",
        weight_kg="82.00",
    )
    await create_weight(
        api_client,
        recorded_on="2026-07-24",
        weight_kg="81.75",
    )

    filtered = await api_client.get(
        "/api/v1/health/weights",
        params={"start_date": "2026-07-21", "end_date": "2026-07-23"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == middle["id"]

    page = await api_client.get(
        "/api/v1/health/weights",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["items"][0]["id"] == middle["id"]

    fetched = await api_client.get(f"/api/v1/health/weights/{first['id']}")
    assert fetched.status_code == 200
    assert Decimal(fetched.json()["weight_kg"]) == Decimal("82.40")

    updated = await api_client.patch(
        f"/api/v1/health/weights/{first['id']}",
        json={"weight_kg": "82.10", "notes": "Morning measurement"},
    )
    assert updated.status_code == 200, updated.text
    assert Decimal(updated.json()["weight_kg"]) == Decimal("82.10")
    assert updated.json()["notes"] == "Morning measurement"

    deleted = await api_client.delete(f"/api/v1/health/weights/{first['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/health/weights/{first['id']}")
    ).status_code == 404


async def test_nutrition_crud_filters_and_pagination(api_client: AsyncClient) -> None:
    first = await create_nutrition(
        api_client,
        recorded_on="2026-07-20",
        calories=2000,
    )
    middle = await create_nutrition(
        api_client,
        recorded_on="2026-07-22",
        calories=2100,
    )
    await create_nutrition(
        api_client,
        recorded_on="2026-07-24",
        calories=2200,
    )

    filtered = await api_client.get(
        "/api/v1/health/nutrition",
        params={"start_date": "2026-07-21", "end_date": "2026-07-23"},
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == middle["id"]

    page = await api_client.get(
        "/api/v1/health/nutrition",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200
    assert page.json()["total"] == 3
    assert page.json()["items"][0]["id"] == middle["id"]

    fetched = await api_client.get(f"/api/v1/health/nutrition/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["calories"] == 2000

    updated = await api_client.patch(
        f"/api/v1/health/nutrition/{first['id']}",
        json={"calories": 2050, "notes": "Added snack"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["calories"] == 2050
    assert updated.json()["notes"] == "Added snack"

    deleted = await api_client.delete(f"/api/v1/health/nutrition/{first['id']}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/health/nutrition/{first['id']}")
    ).status_code == 404


async def test_health_summary_respects_date_range(api_client: AsyncClient) -> None:
    await create_weight(
        api_client,
        recorded_on="2026-07-20",
        weight_kg="82.40",
    )
    await create_weight(
        api_client,
        recorded_on="2026-07-24",
        weight_kg="81.75",
    )
    await create_weight(
        api_client,
        recorded_on="2026-08-01",
        weight_kg="80.00",
    )
    await create_nutrition(
        api_client,
        recorded_on="2026-07-20",
        calories=2000,
        calorie_target=2200,
    )
    await create_nutrition(
        api_client,
        recorded_on="2026-07-24",
        calories=2200,
        calorie_target=2200,
    )
    await create_nutrition(
        api_client,
        recorded_on="2026-08-01",
        calories=999,
        calorie_target=2000,
    )

    response = await api_client.get(
        "/api/v1/health/summary",
        params={"start_date": "2026-07-01", "end_date": "2026-07-31"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(body["latest_weight_kg"]) == Decimal("81.75")
    assert Decimal(body["weight_change_kg"]) == Decimal("-0.65")
    assert body["nutrition_days_logged"] == 2
    assert body["total_calories"] == 4200
    assert Decimal(body["average_daily_calories"]) == Decimal("2100.00")
    assert Decimal(body["average_calorie_target"]) == Decimal("2200.00")


async def test_health_validation_and_missing_resources(api_client: AsyncClient) -> None:
    assert (
        await api_client.post(
            "/api/v1/health/weights",
            json={
                "recorded_on": "2026-07-20",
                "weight_kg": 0,
                "unexpected": True,
            },
        )
    ).status_code == 422
    assert (
        await api_client.post(
            "/api/v1/health/nutrition",
            json={"recorded_on": "2026-07-20", "calories": -1},
        )
    ).status_code == 422
    for path in (
        "/api/v1/health/weights",
        "/api/v1/health/nutrition",
        "/api/v1/health/summary",
    ):
        assert (
            await api_client.get(
                path,
                params={"start_date": "2026-08-01", "end_date": "2026-07-01"},
            )
        ).status_code == 422

    weight = await create_weight(
        api_client,
        recorded_on="2026-07-20",
        weight_kg="82.40",
    )
    nutrition = await create_nutrition(
        api_client,
        recorded_on="2026-07-20",
        calories=2000,
    )
    for path in (
        f"/api/v1/health/weights/{weight['id']}",
        f"/api/v1/health/nutrition/{nutrition['id']}",
    ):
        assert (await api_client.patch(path, json={})).status_code == 422

    assert (
        await api_client.patch(
            f"/api/v1/health/weights/{weight['id']}",
            json={"weight_kg": None},
        )
    ).status_code == 422
    assert (
        await api_client.patch(
            f"/api/v1/health/nutrition/{nutrition['id']}",
            json={"calories": None},
        )
    ).status_code == 422

    missing_id = uuid4()
    for path in (
        f"/api/v1/health/weights/{missing_id}",
        f"/api/v1/health/nutrition/{missing_id}",
    ):
        assert (await api_client.get(path)).status_code == 404
        assert (await api_client.delete(path)).status_code == 404
