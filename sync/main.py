import json
from pathlib import Path
import subprocess
from datetime import datetime
import tarfile
import shutil
import os
import stat
from datetime import datetime
from zoneinfo import ZoneInfo

#googleライブラリ
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# 読み取り専用解除関数
def remove_readonly(func, path, exc):
    # 読み取り専用属性を解除
    os.chmod(path, stat.S_IWRITE)

    # 削除を再実行
    func(path)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# 指定フォルダがない場合に作成する関数
def get_or_create_folder(service, folder_name):
    # 指定フォルダを検索
    query = (
        f"name = '{folder_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "'root' in parents and "
        "trashed = false"
    )

    result = service.files().list(
        q=query,
        fields="files(id, name)"
    ).execute()

    folders = result.get("files", [])

    # 既存フォルダを使用
    if folders:
        return folders[0]["id"]

    # 存在しなければ作成
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["root"]
    }

    folder = service.files().create(
        body=metadata,
        fields="id"
    ).execute()

    return folder["id"]

def main(archive_path):
    creds = None

    token_path = base_dir.parent / "config" / "token.json"
    credentials_path = base_dir.parent / "config" / "credentials.json"

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with token_path.open("w", encoding="utf-8") as token:
            token.write(creds.to_json())

    try:
        service = build("drive", "v3", credentials=creds)

        # 保存先フォルダを取得、存在しなければ作成
        folder_id = get_or_create_folder(
            service,
            "GitHubBackupData"
        )

        # 保存先を指定
        file_metadata = {
            "name": archive_path.name,
            "parents": [folder_id]
        }

        media = MediaFileUpload(
            str(archive_path),
            mimetype = "application/gzip",
            resumable = True
        )

        # Google Driveにアップロード
        file = service.files().create(
            body = file_metadata,
            media_body = media,
            fields = "id, name" 
        ).execute()

        print("Google Driveへのアップロード完了")
        print("ファイル名 : ",file.get("name"))
        print("ファイルID : ",file.get("id"))

    except HttpError as error:
        print("Google Driveエラー" ,error)

#pathlibの使い方難しいなんやこれ

# main.pyが存在するディレクトリを取得
base_dir = Path(__file__).resolve().parent

# configフォルダ内のJSONファイルを指定
json_path = base_dir.parent / "config" / "repositories.json"

# JSONを読み込む
with json_path.open("r", encoding="utf-8") as f:
    repositories = json.load(f) 

repository = repositories["GitHubBackup"]

if repository["isBackup"]:
    name = repository["repositoriName"]
    url = repository["URL"]

    # 保存名を日付でするために現在時刻を取得する
    # 同じ名前だと重複してエラーが起きてしまう可能性があるため
   # 日本時間を取得
    now = datetime.now(ZoneInfo("Asia/Tokyo"))

    date = now.strftime("%Y年%m月%d日%H時%M分%S秒")

    # Dataフォルダ
    data_dir = base_dir.parent / "Data"
    data_dir.mkdir(exist_ok=True)

    # リポジトリごとのフォルダ
    name_dir = data_dir / name

    # 日付ごとのフォルダ
    date_dir = name_dir / date
    # 親フォルダが存在しなくても作成してくれる
    date_dir.mkdir(parents=True, exist_ok=True)

    # 保存先
    backup_path = date_dir / f"{date} + {name}.git"

    print("保存先:", backup_path)

    # クローン
    subprocess.run(["git", "clone", "--mirror", url, str(backup_path)],check=True)

    # 圧縮ファイルの保存先
    archive_path = date_dir / f"{date}_{name}.git.tar.gz"

    backup_success = False

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=backup_path.name)

        with tarfile.open(archive_path, "r:gz") as tar:
            members = tar.getmembers()

            # 全ファイルを読み込んで検証
            for member in members:
                if member.isfile():
                    f = tar.extractfile(member)
                    if f is None:
                        raise tarfile.TarError("ファイルを読み込めません")

                    while f.read(1024 * 1024):
                        pass

        print("圧縮・検証完了")
        backup_success = True

    except (OSError, EOFError, tarfile.TarError) as e:
        print("圧縮・検証失敗:", e)

    if backup_success:
        shutil.rmtree(backup_path, onexc=remove_readonly)
        main(archive_path)

else:
    print("バックアップ対象外です")






  
