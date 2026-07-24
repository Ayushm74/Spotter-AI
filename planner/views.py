from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .services import plan_trip as build_plan


REQUIRED_FIELDS = ("currentLocation", "pickupLocation", "dropoffLocation")


@api_view(["POST"])
def plan_trip(request):
    missing = [field for field in REQUIRED_FIELDS if not request.data.get(field)]
    if missing:
        return Response({"detail": f"Missing required field(s): {', '.join(missing)}"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        cycle = float(request.data.get("currentCycleUsed", 0))
    except (TypeError, ValueError):
        return Response({"detail": "Current cycle used must be a number."}, status=status.HTTP_400_BAD_REQUEST)

    if cycle < 0 or cycle > 70:
        return Response({"detail": "Current cycle used must be between 0 and 70 hours."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        return Response(build_plan(request.data))
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
