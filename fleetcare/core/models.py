from django.db import models
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
import os
import httpx
from django.utils import timezone


# Для слота
class SlotStatus(models.TextChoices):
    FREE = "free", _("Свободен")
    BUSY = "busy", _("Занят")


# Для записи
class AppointmentStatus(models.TextChoices):
    ACTIVE = "active", _("Активна")
    CANCELLED_MANAGER = "cancelled_manager", _("Отменена менеджером")
    CANCELLED_USER = "cancelled_user", _("Отменена пользователем")


# Автомобиль
class Automobile(models.Model):
    plate_number = models.CharField("Госномер", max_length=16, unique=True)
    make = models.CharField("Марка", max_length=64)
    model = models.CharField("Модель", max_length=64)
    last_service_mileage = models.PositiveIntegerField(
        "Пробег последнего ТО", validators=[MinValueValidator(0)]
    )
    service_interval_km = models.PositiveIntegerField(
        "Интервал ТО км", default=10000, validators=[MinValueValidator(1000)]
    )
    next_service_mileage = models.PositiveIntegerField(
        "Пробег следующего ТО", editable=False, default=0
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Автомобиль"
        verbose_name_plural = "Автомобили"
        ordering = ["plate_number"]

    def __str__(self):
        return f"{self.plate_number} {self.make} {self.model}"

    def recalc_next_service(self):

        # Пересчет следующего пробега
        self.next_service_mileage = self.last_service_mileage + self.service_interval_km

    def save(self, *args, **kwargs):

        # Гарантия перерасчета при каждом сохранении
        self.recalc_next_service()
        super().save(*args, **kwargs)


# Водитель
class Driver(models.Model):

    # Привязка один к одному к автомобилю
    first_name = models.CharField("Имя", max_length=64)
    last_name = models.CharField("Фамилия", max_length=64)
    phone = models.CharField("Телефон", max_length=32, unique=True)
    car = models.OneToOneField(
        Automobile,
        on_delete=models.PROTECT,
        related_name="driver",
        verbose_name="Привязанный автомобиль",
    )
    chat_id = models.BigIntegerField("Telegram chat ID", null=True, blank=True)

    class Meta:
        verbose_name = "Водитель"
        verbose_name_plural = "Водители"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name} {self.first_name}"


# Слот
class Slot(models.Model):
    date = models.DateField("Дата")
    time = models.TimeField("Время")
    status = models.CharField(
        "Статус", max_length=8, choices=SlotStatus.choices, default=SlotStatus.FREE
    )

    class Meta:
        verbose_name = "Слот для записи"
        verbose_name_plural = "Слоты для записи"
        unique_together = [("date", "time")]
        ordering = ["date", "time"]

    def __str__(self):
        return f"{self.date} {self.time}"


# Запись
class Appointment(models.Model):
    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, verbose_name="Слот")
    driver = models.ForeignKey(
        Driver, on_delete=models.PROTECT, verbose_name="Водитель"
    )
    car = models.ForeignKey(
        Automobile, on_delete=models.PROTECT, verbose_name="Автомобиль"
    )
    status = models.CharField(
        "Статус",
        max_length=32,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.ACTIVE,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Запись"
        verbose_name_plural = "Записи"
        ordering = ["slot__date", "slot__time"]

    def __str__(self):
        return f"{self.slot} — {self.driver} — {self.car}"

    def clean(self):

        # Проверка соответствия автомобиля водителю
        if self.driver and self.car and self.driver.car_id != self.car_id:
            from django.core.exceptions import ValidationError

            raise ValidationError("Выбранный автомобиль не привязан к этому водителю")

        # Проверка доступности слота
        if self.slot and self.id is None and self.slot.status != SlotStatus.FREE:
            from django.core.exceptions import ValidationError

            raise ValidationError("Выбранный слот уже занят")

    def save(self, *args, **kwargs):

        # Автоматическое управление статусом слота
        creating = self.id is None
        prev = None
        if not creating:
            prev = Appointment.objects.get(pk=self.id)
        super().save(*args, **kwargs)

        # Если новая активная запись то занимаем слот
        if creating and self.status == AppointmentStatus.ACTIVE:
            if self.slot.status != SlotStatus.BUSY:
                self.slot.status = SlotStatus.BUSY
                self.slot.save(update_fields=["status"])

        # Если статус изменен на отмену то освобождаем слот
        if prev and prev.status != self.status:
            if self.status in (
                AppointmentStatus.CANCELLED_MANAGER,
                AppointmentStatus.CANCELLED_USER,
            ):
                if self.slot.status != SlotStatus.FREE:
                    self.slot.status = SlotStatus.FREE
                    self.slot.save(update_fields=["status"])
                send_bot_notification(
                    self.driver,
                    f"Ваша запись на {self.slot.date} {self.slot.time} отменена",
                )


# Простая модель уведомлений
class Notification(models.Model):
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    text = models.TextField("Текст")
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at} {self.driver} {self.text[:32]}"


# Отправка уведомления водителю в Telegram и запись в журнал Notification
def send_bot_notification(driver: "Driver", text: str):

    # 1. Сохраняем уведомление в БД (для менеджера в админке)
    from .models import Notification

    Notification.objects.create(driver=driver, text=text, created_at=timezone.now())

    # 2. Пытаемся отправить сообщение через Telegram Bot API
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("TELEGRAM_BOT_TOKEN не задан, сообщение не отправлено.")
        return
    if not driver.chat_id:
        print(f"У водителя {driver} нет chat_id - невозможно отправить сообщение.")
        return
    message = f"{text}"
    try:
        # Используем httpx с таймаутом и обработкой ошибок
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": driver.chat_id, "text": message}
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(api_url, json=payload)
            if resp.status_code != 200:
                print(f"Ошибка Telegram API: {resp.status_code} -> {resp.text}")
            else:
                print(f"Уведомление отправлено водителю {driver} ({driver.chat_id})")
    except Exception as e:
        print(f"Ошибка при отправке уведомления: {e}")
