from django.http import StreamingHttpResponse
import gzip
import os
import queue
import tarfile
import threading


class QueueBuffer:
    def __init__(self, q):
        self.q = q

    def write(self, data):
        if data:
            self.q.put(data)


def get_directory_as_archive_response(dirs, archive_name):
    q = queue.Queue(maxsize=100)

    def produce_tar():
        raw_stream = QueueBuffer(q)
        with gzip.GzipFile(fileobj=raw_stream, mode="wb", compresslevel=1) as gz_sock:
            with tarfile.open(fileobj=gz_sock, mode="w|") as tar:
                for item in dirs:
                    if isinstance(item, tuple):
                        path, name = item
                    else:
                        path = item.rstrip("/")
                        name = os.path.basename(path)

                    if os.path.isdir(path):
                        tar.add(path, name)
        q.put(None)

    def file_iterator():
        thread = threading.Thread(target=produce_tar)
        thread.start()
        while True:
            chunk = q.get()
            if chunk is None:
                break
            yield chunk

    response = StreamingHttpResponse(file_iterator(), content_type="application/gzip")
    response["Content-Disposition"] = f'attachment; filename="{archive_name}.tar.gz"'
    return response
