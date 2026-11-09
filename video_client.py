import os
import requests

def UploadVideo(server_url: str, video_path: str, company_name: str) -> str:
    """
    Uploads a video file (and its zoom sidecar, if present) to the server.
    Returns the original video URL.
    """
    url = f"{server_url.rstrip('/')}/upload"
    filename = video_path.replace('\\', '/').split('/')[-1]
    
    files = {}
    file_obj = open(video_path, 'rb')
    files['file'] = (filename, file_obj)
    
    sidecar_path = video_path + ".zoom.json"
    sidecar_obj = None
    if os.path.exists(sidecar_path):
        sidecar_obj = open(sidecar_path, 'rb')
        files['sidecar'] = ('sidecar.json', sidecar_obj)
    
    data = {'company_name': company_name}
    
    try:
        response = requests.post(url, files=files, data=data)
        response.raise_for_status()
        return response.json()["video_url"]
    finally:
        # Обязательно закрываем файлы, чтобы не было утечек памяти
        file_obj.close()
        if sidecar_obj:
            sidecar_obj.close()


def GetVideoURL(server_url: str, company_name: str) -> str:
    """
    Returns the video URL for the given company name.
    """
    url = f"{server_url.rstrip('/')}/get_video_url"
    response = requests.get(url, params={"company_name": company_name})
    response.raise_for_status()
    return response.json()["video_url"]