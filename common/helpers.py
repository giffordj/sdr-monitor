from django.http import FileResponse, HttpResponse, StreamingHttpResponse
import mimetypes
import os


def file_response(filename, download_filename=None, remove=True):
    mime = mimetypes.MimeTypes()
    content_type = mime.guess_type(filename)[0]
    if not download_filename:
        download_filename = filename
    response = FileResponse(open(filename, "rb"), content_type=content_type, filename=download_filename)
    if remove:
        os.remove(filename)
    return response


def redirect_file_response(filename, url):
    response = HttpResponse()
    response["Content-Type"] = "application/octet-stream"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["X-Accel-Redirect"] = url
    return response


def streaming_file_response(filename, stream, length=0):
    response = StreamingHttpResponse(stream)
    response["Content-Type"] = "application/octet-stream"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    if 0 < length:
        response["Content-Length"] = length
    return response


def is_json_request(request):
    return "application/json" in request.headers.get("Accept", "")
