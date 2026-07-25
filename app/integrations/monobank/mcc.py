DINING_MCCS = {5811, 5812, 5813, 5814}
GROCERY_MCCS = {5297, 5298, 5411, 5422, 5441, 5451, 5462, 5499}
FUEL_MCCS = {5172, 5541, 5542, 5983}
TRANSPORT_MCCS = {
    4011,
    4111,
    4112,
    4121,
    4131,
    4214,
    4215,
    4784,
    4789,
    7512,
    7523,
}
UTILITIES_MCCS = {4812, 4814, 4816, 4821, 4899, 4900}
TRANSFER_MCCS = {4829, 6012, 6051, 6211, 6536, 6537, 6538, 6539, 6540}
CASH_MCCS = {6010, 6011}
HEALTH_MCCS = {
    5047,
    5122,
    5912,
    5975,
    5976,
    8011,
    8021,
    8031,
    8041,
    8042,
    8043,
    8049,
    8050,
    8062,
    8071,
    8099,
}
EDUCATION_MCCS = {8211, 8220, 8241, 8244, 8249, 8299}
ENTERTAINMENT_MCCS = {
    5733,
    5735,
    5815,
    5816,
    5817,
    5818,
    7832,
    7841,
    7911,
    7922,
    7929,
    7932,
    7933,
    7941,
    7991,
    7996,
    7997,
    7999,
}


def category_for_mcc(mcc: int | None) -> str:
    if mcc is None:
        return "uncategorized"
    if mcc in DINING_MCCS:
        return "dining"
    if mcc in GROCERY_MCCS:
        return "groceries"
    if mcc in FUEL_MCCS:
        return "fuel"
    if mcc in TRANSPORT_MCCS:
        return "transport"
    if mcc in UTILITIES_MCCS:
        return "utilities"
    if mcc in TRANSFER_MCCS:
        return "transfers"
    if mcc in CASH_MCCS:
        return "cash"
    if mcc in HEALTH_MCCS:
        return "health"
    if mcc in EDUCATION_MCCS:
        return "education"
    if mcc in ENTERTAINMENT_MCCS:
        return "entertainment"
    if 3000 <= mcc <= 3999 or mcc in {4411, 4511, 4582, 4722, 7011}:
        return "travel"
    if 5000 <= mcc <= 5999:
        return "shopping"
    if 7000 <= mcc <= 7299:
        return "services"
    return "uncategorized"
