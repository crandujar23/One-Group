from urllib.parse import parse_qs
from urllib.parse import parse_qsl
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import BusinessUnit


class CalendarEvent(models.Model):
    class EventKind(models.TextChoices):
        EVENT = "event", "Evento"
        APPOINTMENT = "appointment", "Cita"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_events")
    business_units = models.ManyToManyField(BusinessUnit, blank=True, related_name="calendar_events")
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    all_day = models.BooleanField(default=False)
    color = models.CharField(max_length=7, default="#1a73e8")
    kind = models.CharField(max_length=20, choices=EventKind.choices, default=EventKind.EVENT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return self.title


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "Por hacer"
        IN_PROGRESS = "in_progress", "En progreso"
        DONE = "done", "Completada"

    class Priority(models.TextChoices):
        LOW = "low", "Baja"
        MEDIUM = "medium", "Media"
        HIGH = "high", "Alta"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    business_units = models.ManyToManyField(BusinessUnit, blank=True, related_name="tasks")
    title = models.CharField(max_length=140)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["due_at"]

    def __str__(self):
        return self.title

    def set_status(self, new_status):
        self.status = new_status
        self.completed_at = timezone.now() if new_status == self.Status.DONE else None


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Programada"
        CONFIRMED = "confirmed", "Confirmada"
        COMPLETED = "completed", "Completada"
        CANCELLED = "cancelled", "Cancelada"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="appointments")
    business_units = models.ManyToManyField(BusinessUnit, blank=True, related_name="appointments")
    subject = models.CharField(max_length=140)
    contact_name = models.CharField(max_length=120)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    location = models.CharField(max_length=140, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]

    def __str__(self):
        return f"{self.subject} - {self.contact_name}"


class SharedResource(models.Model):
    class ResourceType(models.TextChoices):
        FILE = "file", "Archivo"
        VIDEO = "video", "Video"

    ALLOWED_FILE_EXTENSIONS = {".pdf", ".ppt", ".pptx"}
    MAX_FILE_SIZE = 25 * 1024 * 1024

    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    provider = models.CharField(max_length=120, blank=True, default="Interno")
    is_active = models.BooleanField(default=True)
    resource_type = models.CharField(max_length=10, choices=ResourceType.choices)
    file = models.FileField(upload_to="tools/resources/", blank=True, null=True)
    video_url = models.URLField(blank=True)
    tags = models.ManyToManyField("ResourceTag", related_name="resources", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shared_resources")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_pdf(self):
        return self.file and self.file.name.lower().endswith(".pdf")

    @property
    def is_presentation(self):
        return self.file and (self.file.name.lower().endswith(".ppt") or self.file.name.lower().endswith(".pptx"))

    @property
    def source_label(self):
        if self.resource_type == self.ResourceType.VIDEO:
            return "Video"
        if self.is_pdf:
            return "PDF"
        if self.is_presentation:
            return "Presentacion"
        return "Archivo"

    def clean(self):
        super().clean()
        if self.resource_type == self.ResourceType.FILE:
            if not self.file:
                raise ValidationError({"file": "Debes subir un archivo PDF o PPT."})
            if self.video_url:
                raise ValidationError({"video_url": "No combines archivo y enlace de video en el mismo recurso."})
            file_name = (self.file.name or "").lower()
            if not any(file_name.endswith(ext) for ext in self.ALLOWED_FILE_EXTENSIONS):
                raise ValidationError({"file": "Solo se permiten archivos PDF, PPT y PPTX."})
            if self.file.size > self.MAX_FILE_SIZE:
                raise ValidationError({"file": "El archivo no puede superar 25MB."})

        if self.resource_type == self.ResourceType.VIDEO:
            if not self.video_url:
                raise ValidationError({"video_url": "Debes agregar el enlace del video."})
            if self.file:
                raise ValidationError({"file": "Un recurso de video no debe incluir archivo adjunto."})
            if not self._video_embed_url():
                raise ValidationError({"video_url": "El enlace debe ser de YouTube, Vimeo, Loom o Google Drive."})

    def _video_embed_url(self):
        if not self.video_url:
            return None

        parsed = urlparse(self.video_url.strip())
        host = parsed.netloc.lower().replace("www.", "")
        path_parts = [part for part in parsed.path.split("/") if part]
        query_params = parse_qs(parsed.query)

        if host in {"youtube.com", "m.youtube.com"}:
            if parsed.path.startswith("/watch"):
                video_id = parse_qs(parsed.query).get("v", [None])[0]
                if video_id:
                    return f"https://www.youtube.com/embed/{video_id}"
            if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts"}:
                return f"https://www.youtube.com/embed/{path_parts[1]}"

        if host == "youtu.be" and path_parts:
            return f"https://www.youtube.com/embed/{path_parts[0]}"

        if host == "vimeo.com" and path_parts:
            return f"https://player.vimeo.com/video/{path_parts[0]}"

        if host == "loom.com" and len(path_parts) >= 2 and path_parts[0] == "share":
            return f"https://www.loom.com/embed/{path_parts[1]}"

        if host in {"drive.google.com", "docs.google.com"}:
            file_id = None
            extra = []
            if len(path_parts) >= 3 and path_parts[0] == "file" and path_parts[1] == "d":
                file_id = path_parts[2]
            if not file_id:
                file_id = query_params.get("id", [None])[0]
            resource_key = query_params.get("resourcekey", [None])[0]
            auth_user = query_params.get("authuser", [None])[0]
            if resource_key:
                extra.append(f"resourcekey={resource_key}")
            if auth_user:
                extra.append(f"authuser={auth_user}")
            if file_id:
                suffix = f"?{'&'.join(extra)}" if extra else ""
                return f"https://drive.google.com/file/d/{file_id}/preview{suffix}"

        return None

    def get_embed_url(self, request=None):
        if self.resource_type == self.ResourceType.VIDEO:
            embed_url = self._video_embed_url()
            if not embed_url:
                return None

            parsed = urlparse(embed_url)
            host = parsed.netloc.lower().replace("www.", "")
            if host == "youtube.com" and parsed.path.startswith("/embed/") and request is not None:
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                params["origin"] = request.build_absolute_uri("/")[:-1]
                params["widget_referrer"] = request.build_absolute_uri()
                query = urlencode(params)
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))

            return embed_url

        if self.resource_type != self.ResourceType.FILE or not self.file:
            return None

        file_url = self.file.url
        absolute_url = request.build_absolute_uri(file_url) if request else None

        if self.is_pdf:
            return absolute_url or file_url

        if self.is_presentation and absolute_url:
            return f"https://view.officeapps.live.com/op/embed.aspx?src={quote(absolute_url, safe='')}"

        return None


class ResourceTag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Announcement(models.Model):
    class MediaType(models.TextChoices):
        NONE = "none", "Sin medio"
        PDF = "pdf", "PDF"
        VIDEO = "video", "Video"
        IMAGE = "image", "Imagen"

    MAX_PDF_SIZE = 30 * 1024 * 1024
    MAX_IMAGE_SIZE = 8 * 1024 * 1024
    PDF_EXTENSIONS = {".pdf"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    title = models.CharField(max_length=160)
    message = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.NONE)
    media_file = models.FileField(upload_to="announcements/", blank=True, null=True)
    video_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcements")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fecha de finalizacion debe ser igual o posterior a la de implementacion."})

        file_name = (self.media_file.name or "").lower() if self.media_file else ""

        if self.media_type == self.MediaType.NONE:
            if self.media_file or self.video_url:
                raise ValidationError("Si seleccionas 'Sin medio', no agregues archivo ni enlace.")
            return

        if self.media_type == self.MediaType.PDF:
            if not self.media_file:
                raise ValidationError({"media_file": "Debes subir un archivo PDF."})
            if self.video_url:
                raise ValidationError({"video_url": "No combines PDF y enlace de video en el mismo anuncio."})
            if not any(file_name.endswith(ext) for ext in self.PDF_EXTENSIONS):
                raise ValidationError({"media_file": "Solo se permite archivo PDF para este tipo de anuncio."})
            if self.media_file.size > self.MAX_PDF_SIZE:
                raise ValidationError({"media_file": "El PDF no puede superar 30MB."})
            return

        if self.media_type == self.MediaType.IMAGE:
            if not self.media_file:
                raise ValidationError({"media_file": "Debes subir una imagen."})
            if self.video_url:
                raise ValidationError({"video_url": "No combines imagen y enlace de video en el mismo anuncio."})
            if not any(file_name.endswith(ext) for ext in self.IMAGE_EXTENSIONS):
                raise ValidationError({"media_file": "Solo se permiten imagenes JPG, JPEG, PNG, WEBP o GIF."})
            if self.media_file.size > self.MAX_IMAGE_SIZE:
                raise ValidationError({"media_file": "La imagen no puede superar 8MB."})
            return

        if self.media_type == self.MediaType.VIDEO:
            if self.media_file:
                raise ValidationError({"media_file": "Un anuncio de video no debe incluir archivo adjunto."})
            if not self.video_url:
                raise ValidationError({"video_url": "Debes agregar el enlace de video."})
            if not self._video_embed_url():
                raise ValidationError({"video_url": "El enlace debe ser de YouTube o Google Drive."})
            return

    def _video_embed_url(self):
        if not self.video_url:
            return None

        parsed = urlparse(self.video_url.strip())
        host = parsed.netloc.lower().replace("www.", "")
        path_parts = [part for part in parsed.path.split("/") if part]
        query_params = parse_qs(parsed.query)

        if host in {"youtube.com", "m.youtube.com"}:
            if parsed.path.startswith("/watch"):
                video_id = query_params.get("v", [None])[0]
                if video_id:
                    return f"https://www.youtube.com/embed/{video_id}"
            if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts"}:
                return f"https://www.youtube.com/embed/{path_parts[1]}"

        if host == "youtu.be" and path_parts:
            return f"https://www.youtube.com/embed/{path_parts[0]}"

        if host in {"drive.google.com", "docs.google.com"}:
            file_id = None
            extra = []
            if len(path_parts) >= 3 and path_parts[0] == "file" and path_parts[1] == "d":
                file_id = path_parts[2]
            if not file_id:
                file_id = query_params.get("id", [None])[0]
            resource_key = query_params.get("resourcekey", [None])[0]
            auth_user = query_params.get("authuser", [None])[0]
            if resource_key:
                extra.append(f"resourcekey={resource_key}")
            if auth_user:
                extra.append(f"authuser={auth_user}")
            if file_id:
                suffix = f"?{'&'.join(extra)}" if extra else ""
                return f"https://drive.google.com/file/d/{file_id}/preview{suffix}"

        return None

    def get_video_embed_url(self, request=None):
        embed_url = self._video_embed_url()
        if not embed_url:
            return None

        parsed = urlparse(embed_url)
        host = parsed.netloc.lower().replace("www.", "")
        if host == "youtube.com" and parsed.path.startswith("/embed/") and request is not None:
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            params["origin"] = request.build_absolute_uri("/")[:-1]
            params["widget_referrer"] = request.build_absolute_uri()
            query = urlencode(params)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
        return embed_url


class Offer(models.Model):
    class MediaType(models.TextChoices):
        NONE = "none", "Sin medio"
        PDF = "pdf", "PDF"
        VIDEO = "video", "Video"
        IMAGE = "image", "Imagen"

    MAX_PDF_SIZE = 30 * 1024 * 1024
    MAX_IMAGE_SIZE = 8 * 1024 * 1024
    PDF_EXTENSIONS = {".pdf"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    title = models.CharField(max_length=160)
    message = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    media_type = models.CharField(max_length=10, choices=MediaType.choices, default=MediaType.NONE)
    media_file = models.FileField(upload_to="offers/", blank=True, null=True)
    video_url = models.URLField(blank=True)
    business_units = models.ManyToManyField(BusinessUnit, related_name="offers", blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="offers")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "La fecha de finalizacion debe ser igual o posterior a la de implementacion."})

        file_name = (self.media_file.name or "").lower() if self.media_file else ""

        if self.media_type == self.MediaType.NONE:
            if self.media_file or self.video_url:
                raise ValidationError("Si seleccionas 'Sin medio', no agregues archivo ni enlace.")
            return

        if self.media_type == self.MediaType.PDF:
            if not self.media_file:
                raise ValidationError({"media_file": "Debes subir un archivo PDF."})
            if self.video_url:
                raise ValidationError({"video_url": "No combines PDF y enlace de video en la misma oferta."})
            if not any(file_name.endswith(ext) for ext in self.PDF_EXTENSIONS):
                raise ValidationError({"media_file": "Solo se permite archivo PDF para este tipo de oferta."})
            if self.media_file.size > self.MAX_PDF_SIZE:
                raise ValidationError({"media_file": "El PDF no puede superar 30MB."})
            return

        if self.media_type == self.MediaType.IMAGE:
            if not self.media_file:
                raise ValidationError({"media_file": "Debes subir una imagen."})
            if self.video_url:
                raise ValidationError({"video_url": "No combines imagen y enlace de video en la misma oferta."})
            if not any(file_name.endswith(ext) for ext in self.IMAGE_EXTENSIONS):
                raise ValidationError({"media_file": "Solo se permiten imagenes JPG, JPEG, PNG, WEBP o GIF."})
            if self.media_file.size > self.MAX_IMAGE_SIZE:
                raise ValidationError({"media_file": "La imagen no puede superar 8MB."})
            return

        if self.media_type == self.MediaType.VIDEO:
            if self.media_file:
                raise ValidationError({"media_file": "Una oferta de video no debe incluir archivo adjunto."})
            if not self.video_url:
                raise ValidationError({"video_url": "Debes agregar el enlace de video."})
            if not self._video_embed_url():
                raise ValidationError({"video_url": "El enlace debe ser de YouTube o Google Drive."})
            return

    def _video_embed_url(self):
        if not self.video_url:
            return None

        parsed = urlparse(self.video_url.strip())
        host = parsed.netloc.lower().replace("www.", "")
        path_parts = [part for part in parsed.path.split("/") if part]
        query_params = parse_qs(parsed.query)

        if host in {"youtube.com", "m.youtube.com"}:
            if parsed.path.startswith("/watch"):
                video_id = query_params.get("v", [None])[0]
                if video_id:
                    return f"https://www.youtube.com/embed/{video_id}"
            if len(path_parts) >= 2 and path_parts[0] in {"embed", "shorts"}:
                return f"https://www.youtube.com/embed/{path_parts[1]}"

        if host == "youtu.be" and path_parts:
            return f"https://www.youtube.com/embed/{path_parts[0]}"

        if host in {"drive.google.com", "docs.google.com"}:
            file_id = None
            extra = []
            if len(path_parts) >= 3 and path_parts[0] == "file" and path_parts[1] == "d":
                file_id = path_parts[2]
            if not file_id:
                file_id = query_params.get("id", [None])[0]
            resource_key = query_params.get("resourcekey", [None])[0]
            auth_user = query_params.get("authuser", [None])[0]
            if resource_key:
                extra.append(f"resourcekey={resource_key}")
            if auth_user:
                extra.append(f"authuser={auth_user}")
            if file_id:
                suffix = f"?{'&'.join(extra)}" if extra else ""
                return f"https://drive.google.com/file/d/{file_id}/preview{suffix}"

        return None

    def get_video_embed_url(self, request=None):
        embed_url = self._video_embed_url()
        if not embed_url:
            return None

        parsed = urlparse(embed_url)
        host = parsed.netloc.lower().replace("www.", "")
        if host == "youtube.com" and parsed.path.startswith("/embed/") and request is not None:
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
            params["origin"] = request.build_absolute_uri("/")[:-1]
            params["widget_referrer"] = request.build_absolute_uri()
            query = urlencode(params)
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))
        return embed_url
