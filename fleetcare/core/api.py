from rest_framework import viewsets, routers, mixins
from rest_framework.decorators import action
from rest_framework.response import Response
from datetime import date, timedelta
from .models import Automobile, Driver, Slot, Appointment, SlotStatus, AppointmentStatus
import re
from .serializers import (
    AutomobileSerializer,
    DriverSerializer,
    SlotSerializer,
    AppointmentSerializer,
)


# CRUD над машинами
class AutomobileViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Automobile.objects.all()
    serializer_class = AutomobileSerializer


# CRUD над водителями + метод by_phone для поиска по номеру
class DriverViewSet(viewsets.ModelViewSet):
    queryset = Driver.objects.select_related("car")
    serializer_class = DriverSerializer

    @action(detail=False, methods=["get"])
    def by_phone(self, request):
        phone = (request.query_params.get("phone") or "").strip()
        if not phone:
            return Response({"detail": "phone required"}, status=400)

        # Нормализуем: оставляем только цифры
        norm = re.sub(r"\D+", "", phone)

        # Обходим водителей и сравниваем нормализованные номера
        for d in Driver.objects.select_related("car").all():
            db_norm = re.sub(r"\D+", "", d.phone or "")
            if db_norm == norm:
                return Response(DriverSerializer(d).data)
        return Response({"detail": "not found"}, status=404)


# CRUD над слотами
class SlotViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Slot.objects.all()
    serializer_class = SlotSerializer

    def list(self, request, *args, **kwargs):

        # GET /api/slots?date=YYYY-MM-DD - свободные на дату (если не указана, то все свободные)
        want_date = request.query_params.get("date")
        qs = self.get_queryset().filter(status=SlotStatus.FREE)
        if want_date:
            qs = qs.filter(date=want_date)
        qs = qs.order_by("date", "time")
        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["get"])
    def free_dates(self, request):

        # GET /api/slots/free_dates?days=7 - свободные даты (агрегировано), по умолчанию 7 дней
        days = int(request.query_params.get("days", "7"))
        today = date.today()
        until = today + timedelta(days=days)
        qs = (
            Slot.objects.filter(
                status=SlotStatus.FREE, date__gte=today, date__lte=until
            )
            .values_list("date", flat=True)
            .distinct()
            .order_by("date")
        )
        return Response([str(d) for d in qs])


# CRUD над записями
class AppointmentViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Appointment.objects.select_related("slot", "driver", "car")
    serializer_class = AppointmentSerializer

    @action(detail=False, methods=["get"])
    def active_by_phone(self, request):

        # GET /api/appointments/active_by_phone?phone=+7...
        phone = request.query_params.get("phone")
        if not phone:
            return Response({"detail": "phone required"}, status=400)
        try:
            d = Driver.objects.get(phone=phone)
        except Driver.DoesNotExist:
            return Response({"detail": "driver not found"}, status=404)
        qs = (
            self.get_queryset()
            .filter(driver=d, status=AppointmentStatus.ACTIVE)
            .order_by("slot__date", "slot__time")
        )
        data = []
        for ap in qs:
            data.append(
                {
                    "id": ap.id,
                    "date": str(ap.slot.date),
                    "time": ap.slot.time.strftime("%H:%M"),
                    "car_plate": ap.car.plate_number,
                }
            )
        return Response(data)

    @action(detail=True, methods=["post"])
    def cancel_user(self, request, pk=None):

        # POST /api/appointments/{id}/cancel_user/
        ap = self.get_object()
        ap.status = AppointmentStatus.CANCELLED_USER
        ap.save()
        return Response(self.get_serializer(ap).data)


# Регистрация классов
router = routers.DefaultRouter()
router.register(r"automobiles", AutomobileViewSet, basename="automobiles")
router.register(r"drivers", DriverViewSet, basename="drivers")
router.register(r"slots", SlotViewSet, basename="slots")
router.register(r"appointments", AppointmentViewSet, basename="appointments")
