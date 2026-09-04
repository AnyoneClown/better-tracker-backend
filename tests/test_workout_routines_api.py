from httpx import AsyncClient


def routine_payload(name: str = "My full body") -> dict[str, object]:
    return {
        "name": name,
        "notes": "Three days a week",
        "exercises": [
            {
                "exercise": "Back Squat",
                "set_count": 3,
                "target_reps": 5,
                "target_weight_kg": "80.000",
                "rest_seconds": 180,
            },
            {
                "exercise": "Bench Press",
                "set_count": 3,
                "target_reps": 5,
                "rest_seconds": 180,
            },
        ],
    }


async def test_routine_crud_preserves_order_and_cascades(
    api_client: AsyncClient,
) -> None:
    created = await api_client.post(
        "/api/v1/workout-routines", json=routine_payload()
    )
    assert created.status_code == 201, created.text
    body = created.json()
    routine_id = body["id"]
    assert [item["exercise"] for item in body["exercises"]] == [
        "back squat",
        "bench press",
    ]
    assert [item["position"] for item in body["exercises"]] == [1, 2]

    listed = await api_client.get("/api/v1/workout-routines")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [routine_id]

    update_payload = routine_payload("Updated full body")
    update_payload["exercises"] = list(reversed(update_payload["exercises"]))
    updated = await api_client.patch(
        f"/api/v1/workout-routines/{routine_id}", json=update_payload
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Updated full body"
    assert [item["exercise"] for item in updated.json()["exercises"]] == [
        "bench press",
        "back squat",
    ]

    deleted = await api_client.delete(f"/api/v1/workout-routines/{routine_id}")
    assert deleted.status_code == 204
    assert (
        await api_client.get(f"/api/v1/workout-routines/{routine_id}")
    ).status_code == 404


async def test_routine_validation_rejects_normalized_duplicate_exercises(
    api_client: AsyncClient,
) -> None:
    payload = routine_payload()
    payload["exercises"] = [
        {
            "exercise": " Back   Squat ",
            "set_count": 3,
            "target_reps": 5,
            "rest_seconds": 180,
        },
        {
            "exercise": "back squat",
            "set_count": 4,
            "target_reps": 6,
            "rest_seconds": 120,
        },
    ]
    response = await api_client.post("/api/v1/workout-routines", json=payload)
    assert response.status_code == 422
