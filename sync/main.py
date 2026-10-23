import json
from pathlib import Path
import subprocess
from datetime import datetime
import shutil
import os
import stat
from datetime import datetime
from zoneinfo import ZoneInfo
import zipfile

#googleライブラリ
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# ============================================================
# 読み取り専用属性を解除する関数
# ============================================================
# Gitのミラーリポジトリには、読み取り専用のファイルが含まれている場合がある
#
# shutil.rmtree()で削除に失敗した際に呼び出され、
# ファイルの属性を変更して削除を再実行する。
#
# func : 削除に失敗した処理
# path : 削除対象のファイルパス
# exc  : 発生した例外情報
# ============================================================
def remove_readonly(func, path, exc):
    # 読み取り専用属性を解除
    os.chmod(path, stat.S_IWRITE)

    # 削除を再実行
    func(path)

# ============================================================
# Google Drive APIのアクセス権限
# ============================================================
# drive.file:
# アプリが作成したファイルや、アプリに許可された
# ファイルを操作するための権限。
#
# Google Drive全体へのアクセス権限を持っているわけではないらしい
# ============================================================
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ============================================================
# Google Drive内のバックアップ保存先フォルダを取得する関数
# ============================================================
# service     : 認証済みのGoogle Drive APIサービス
# folder_name : 検索または作成するフォルダ名
#
# 戻り値: Google Drive上のフォルダID
# ============================================================
def get_or_create_folder(service, folder_name):
    # 指定フォルダを検索
    query = (
        f"name = '{folder_name}' and "
        "mimeType = 'application/vnd.google-apps.folder' and "
        "'root' in parents and "
        "trashed = false"
    )

    # Google Driveからフォルダ一覧を取得
    result = service.files().list(q=query,fields="files(id, name)").execute()

    # 検索結果からファイル情報を取得
    # 見つからなかった場合は空リストを使用
    folders = result.get("files", [])

    # フォルダが存在している場合
    if folders:
        return folders[0]["id"]

    # 存在しなければ作成
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": ["root"]
    }

    # Google Driveにフォルダを作成
    folder = service.files().create(
        body=metadata,
        fields="id"
    ).execute()

    # 作成したフォルダのIDを返す
    return folder["id"]

# ============================================================
# Google Driveへバックアップファイルをアップロードする関数
# ============================================================
def main(archive_path):
    # Google認証情報を格納する変数
    creds = None

    # 認証に使用するファイルのパス
    token_path = base_dir.parent / "config" / "token.json"
    credentials_path = base_dir.parent / "config" / "credentials.json"

    # 保存済みの認証トークンが存在する場合
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    # 認証情報が存在しない、または無効な場合
    if not creds or not creds.valid:
        # トークンの期限が切れていて、更新用トークンが存在する場合
        if creds and creds.expired and creds.refresh_token:
             # 認証トークンを更新
            creds.refresh(Request())
        else:
            # 初回認証などの場合 : credentials.jsonからOAuth認証設定を読み込む
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            # ローカルサーバを起動してブラウザ認証、空いてるポートを自動選択
            creds = flow.run_local_server(port=0)
        # 次回以降の認証で再利用するため、取得したトークンを保存
        with token_path.open("w", encoding="utf-8") as token:
            token.write(creds.to_json())

    try:
        # Google Drive API v3のサービスを作成
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

        # アップロードするファイルを準備
        media = MediaFileUpload(
            str(archive_path),
            # ファイルのMIMEタイプ
            mimetype = "application/zip",
            # 分割アップロードを有効化(大容量のファイル転送に利用可能)
            resumable = True
        )

        # Google Driveにアップロード
        file = service.files().create(
            body = file_metadata,
            media_body = media,
            fields = "id, name" 
        ).execute()

        # アップロード結果の通知
        print("Google Driveへのアップロード完了")
        print("ファイル名 : ",file.get("name"))
        print("ファイルID : ",file.get("id"))

    except HttpError as error:
        print("Google Driveエラー" ,error)

#pathlibの使い方難しいなんやこれ

# ============================================================
# バックアップ処理の開始
# ============================================================

# main.pyが存在するディレクトリを取得
base_dir = Path(__file__).resolve().parent

# ============================================================
# バックアップ設定ファイルの読み込み
# ============================================================
# configフォルダ内のJSONファイルを指定
json_path = base_dir.parent / "config" / "repositories.json"

# JSONを読み込む
with json_path.open("r", encoding="utf-8") as f:
    repositories = json.load(f) 

# JSON内のGitHubBackup設定を取得
repository = repositories["GitHubBackup"]

# ============================================================
# バックアップ対象かどうかを判定
# ============================================================
# isBackupがTrueの場合のみバックアップを実行
if repository["isBackup"]:
    name = repository["repositoriName"]
    url = repository["URL"]

    # 保存名を日付でするために現在時刻を取得する
    # 同じ名前だと重複してエラーが起きてしまう可能性があるため
    # 日本時間を取得
    now = datetime.now(ZoneInfo("Asia/Tokyo"))

    # 日時を文字列に変換
    date = now.strftime("%Y年%m月%d日%H時%M分%S秒")

    # ========================================================
    # バックアップ保存先の作成
    # ========================================================

    # Dataフォルダ
    data_dir = base_dir.parent / "Data"
    data_dir.mkdir(exist_ok=True)

    # リポジトリごとのフォルダ
    name_dir = data_dir / name

    # 日付ごとのフォルダ
    date_dir = name_dir / date
    # 親フォルダが存在しなくても作成してくれる
    date_dir.mkdir(parents=True, exist_ok=True)

    # ========================================================
    # Gitリポジトリのミラーバックアップ
    # ========================================================

    # 保存先
    backup_path = date_dir / f"{date} + {name}.git"

    print("保存先:", backup_path)

     # GitコマンドをPythonから実行
    subprocess.run(["git", "clone", "--mirror", url, str(backup_path)],check=True)

    # Gitリポジトリの整合性確認
    subprocess.run(
        ["git", "-C", str(backup_path), "fsck", "--full"],
        check=True
    )

    # ========================================================
    # バックアップファイルの圧縮
    # ========================================================

    # 圧縮ファイルの保存先
    archive_path = date_dir / f"{date}_{name}.git.zip"

    # 圧縮と検証が成功したかを管理する変数
    backup_success = False

try:
    # ====================================================
    # ZIPファイルの作成
    # ====================================================
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED
    ) as zipf:

        # ミラーリポジトリ内のファイル・フォルダを取得
        for file_path in backup_path.rglob("*"):

            # ZIP内の相対パスを取得
            relative_path = file_path.relative_to(backup_path.parent)

            if file_path.is_dir():
                # 空のディレクトリも保存
                zipf.write(
                    file_path,
                    arcname=str(relative_path) + "/"
                )

            elif file_path.is_file():
                # ファイルをZIPに追加
                zipf.write(
                    file_path,
                    arcname=relative_path
                )

    print("ZIP圧縮完了")

    # ====================================================
    # ZIPファイルの整合性確認
    # ====================================================
    with zipfile.ZipFile(archive_path, "r") as zipf:

        # 全ファイルを読み込んでCRCチェック
        bad_file = zipf.testzip()

        # 破損ファイルが見つかった場合
        if bad_file is not None:
            raise ValueError(f"破損ファイル: {bad_file}")

    print("ZIP検証完了")
    backup_success = True

# 圧縮・読み込み・検証時の例外を処理
except (OSError, EOFError, zipfile.BadZipFile, ValueError) as e:
    print("圧縮・検証失敗:", e)

# ========================================================
# バックアップ成功後の後処理
# ========================================================
if backup_success:
    shutil.rmtree(backup_path, onexc=remove_readonly)
    main(archive_path)

# バックアップ対象外の場合
else:
    print("バックアップ対象外です")






  
