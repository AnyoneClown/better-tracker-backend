from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient


async def create_workout(
    client: AsyncClient,
    *,
    name: str,
    performed_at: str,
    duration_minutes: int = 45,
    sets: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/workouts",
        json={
            "name": name,
            "performed_at": performed_at,
            "duration_minutes": duration_minutes,
            "notes": f"Notes for {name}",
            "sets": sets or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_workout_crud_replaces_sets_and_deletes(api_client: AsyncClient) -> None:
    created = await create_workout(
        api_client,
        name="  Strength day  ",
        performed_at="2026-07-20T18:00:00+03:00",
        duration_minutes=60,
        sets=[
            {
                "exercise": " Squat ",
                "set_number": 1,
                "reps": 5,
                "weight_kg": "100.000",
            },
            {
                "exercise": "Run",
                "set_number": 1,
                "distance_km": "5.000",
                "duration_seconds": 1800,
            },
        ],
    )
    workout_id = created["id"]
    assert created["name"] == "Strength day"
    assert {item["exercise"] for item in created["sets"]} == {"run", "squat"}

    fetched = await api_client.get(f"/api/v1/workouts/{workout_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]
    assert fetched.json()["name"] == created["name"]
    assert {item["id"] for item in fetched.json()["sets"]} == {
        item["id"] for item in created["sets"]
    }

    updated = await api_client.patch(
        f"/api/v1/workouts/{workout_id}",
        json={
            "name": "Pull day",
            "duration_minutes": 75,
            "sets": [
                {
                    "exercise": "Deadlift",
                    "set_number": 1,
                    "reps": 3,
                    "weight_kg": "120.000",
                }
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Pull day"
    assert updated.json()["duration_minutes"] == 75
    assert [item["exercise"] for item in updated.json()["sets"]] == ["deadlift"]

    deleted = await api_client.delete(f"/api/v1/workouts/{workout_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert (await api_client.get(f"/api/v1/workouts/{workout_id}")).status_code == 404


async def test_workout_filters_pagination_and_summary(api_client: AsyncClient) -> None:
    await create_workout(
        api_client,
        name="Long session",
        performed_at="2026-07-20T18:00:00+03:00",
        duration_minutes=60,
        sets=[
            {
                "exercise": "squat",
                "set_number": 1,
                "reps": 5,
                "weight_kg": "100.000",
            },
            {
                "exercise": "squat",
                "set_number": 2,
                "reps": 5,
                "weight_kg": "100.000",
            },
            {
                "exercise": "run",
                "set_number": 1,
                "distance_km": "5.000",
                "duration_seconds": 1800,
            },
        ],
    )
    await create_workout(
        api_client,
        name="Short session",
        performed_at="2026-07-22T18:00:00+03:00",
        duration_minutes=30,
        sets=[
            {
                "exercise": "squat",
                "set_number": 1,
                "reps": 10,
                "weight_kg": "50.000",
            }
        ],
    )

    page = await api_client.get(
        "/api/v1/workouts",
        params={"offset": 1, "limit": 1},
    )
    assert page.status_code == 200, page.text
    assert page.json()["total"] == 2
    assert page.json()["offset"] == 1
    assert page.json()["limit"] == 1
    assert [item["name"] for item in page.json()["items"]] == ["Long session"]

    filtered = await api_client.get(
        "/api/v1/workouts",
        params={
            "date_from": "2026-07-21T00:00:00+00:00",
            "date_to": "2026-07-23T00:00:00+00:00",
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["name"] == "Short session"

    summary = await api_client.get("/api/v1/workouts/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["workout_count"] == 2
    assert body["total_duration_minutes"] == 90
    assert Decimal(body["average_duration_minutes"]) == Decimal("45.00")
    assert body["total_sets"] == 4
    assert body["total_reps"] == 20
    assert Decimal(body["total_volume_kg"]) == Decimal("1500.000")
    assert Decimal(body["total_distance_km"]) == Decimal("5.000")
    assert body["total_set_duration_seconds"] == 1800
    exercises = {item["exercise"]: item for item in body["exercises"]}
    assert exercises["squat"]["sets"] == 3
    assert exercises["run"]["distance_km"] == "5.000"


async def test_workout_validation_and_missing_resources(
    api_client: AsyncClient,
) -> None:
    invalid_create = await api_client.post(
        "/api/v1/workouts",
        json={
            "name": "Invalid",
            "performed_at": "2026-07-20T18:00:00",
            "sets": [{"exercise": "squat", "set_number": 1}],
            "unexpected": True,
        },
    )
    assert invalid_create.status_code == 422

    invalid_range = await api_client.get(
        "/api/v1/workouts",
        params={
            "date_from": "2026-07-23T00:00:00+00:00",
            "date_to": "2026-07-21T00:00:00+00:00",
        },
    )
    assert invalid_range.status_code == 422
    assert (
        await api_client.get("/api/v1/workouts", params={"limit": 0})
    ).status_code == 422

    missing_id = uuid4()
    assert (await api_client.get(f"/api/v1/workouts/{missing_id}")).status_code == 404
    assert (
        await api_client.patch(f"/api/v1/workouts/{missing_id}", json={"name": "x"})
    ).status_code == 404
    assert (
        await api_client.delete(f"/api/v1/workouts/{missing_id}")
    ).status_code == 404

    created = await create_workout(
        api_client,
        name="Valid",
        performed_at="2026-07-20T18:00:00+00:00",
    )
    assert (
        await api_client.patch(f"/api/v1/workouts/{created['id']}", json={})
    ).status_code == 422
    assert (
        await api_client.patch(
            f"/api/v1/workouts/{created['id']}",
            json={"name": None},
        )
    ).status_code == 422


async def test_active_workout_autosave_completion_and_history_exclusion(
    api_client: AsyncClient,
) -> None:
    active_payload = {
        "name": "Full Body",
        "performed_at": "2026-07-20T18:00:00+03:00",
        "notes": None,
        "sets": [
            {
                "exercise": "Back Squat",
                "set_number": 1,
                "is_completed": False,
                "rest_seconds": 180,
            },
            {
                "exercise": "Back Squat",
                "set_number": 2,
                "is_completed": False,
                "reps": 5,
                "weight_kg": "100.000",
                "rest_seconds": 180,
            },
            {
                "exercise": "Bench Press",
                "set_number": 1,
                "is_completed": False,
                "reps": 5,
                "weight_kg": "70.000",
                "rest_seconds": 180,
            },
        ],
    }
    created = await api_client.post("/api/v1/workouts/active", json=active_payload)
    assert created.status_code == 201, created.text
    workout_id = created.json()["id"]
    assert created.json()["completed_at"] is None
    assert [item["position"] for item in created.json()["sets"]] == [1, 2, 3]

    duplicate = await api_client.post("/api/v1/workouts/active", json=active_payload)
    assert duplicate.status_code == 409
    assert (await api_client.get("/api/v1/workouts")).json()["total"] == 0
    assert (await api_client.get("/api/v1/workouts/summary")).json()[
        "workout_count"
    ] == 0

    autosave_sets = active_payload["sets"]
    assert isinstance(autosave_sets, list)
    autosave_sets[1]["is_completed"] = True
    saved = await api_client.patch(
        f"/api/v1/workouts/{workout_id}",
        json={
            "rest_timer_ends_at": "2026-07-20T18:03:00+03:00",
            "sets": autosave_sets,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["sets"][1]["is_completed"] is True
    assert saved.json()["rest_timer_ends_at"] is not None

    completed = await api_client.post(f"/api/v1/workouts/{workout_id}/complete")
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["completed_at"] is not None
    assert body["rest_timer_ends_at"] is None
    assert body["duration_minutes"] >= 1
    assert len(body["sets"]) == 1
    assert body["sets"][0]["position"] == 1
    assert body["sets"][0]["set_number"] == 1
    assert (await api_client.get("/api/v1/workouts")).json()["total"] == 1


async def test_active_workout_rejects_invalid_completed_set_and_can_cancel(
    api_client: AsyncClient,
) -> None:
    invalid = await api_client.post(
        "/api/v1/workouts/active",
        json={
            "name": "Invalid",
            "performed_at": "2026-07-20T18:00:00+03:00",
            "sets": [
                {
                    "exercise": "Squat",
                    "set_number": 1,
                    "is_completed": True,
                }
            ],
        },
    )
    assert invalid.status_code == 422

    created = await api_client.post(
        "/api/v1/workouts/active",
        json={
            "name": "Cancelable",
            "performed_at": "2026-07-20T18:00:00+03:00",
            "sets": [
                {
                    "exercise": "Squat",
                    "set_number": 1,
                    "is_completed": False,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    workout_id = created.json()["id"]
    canceled = await api_client.delete(f"/api/v1/workouts/{workout_id}")
    assert canceled.status_code == 204
    assert (await api_client.get("/api/v1/workouts/active")).json() is None
