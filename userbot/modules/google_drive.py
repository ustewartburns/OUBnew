# Copyright (C) 2020 Adek Maulana
#
# SPDX-License-Identifier: GPL-3.0-or-later
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
""" - OUBnew Google Drive managers - """
import io
import os
import pickle
import base64
import json
import asyncio
import math
import time
import re
import heroku3
from os.path import isfile, isdir, join
from mimetypes import guess_type

from telethon import events

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from userbot import (
    G_DRIVE_DATA, G_DRIVE_CLIENT_ID, G_DRIVE_CLIENT_SECRET,
    G_DRIVE_FOLDER_ID, G_DRIVE_AUTH_TOKEN_DATA,
    HEROKU_API_KEY, HEROKU_APP_NAME, BOTLOG_CHATID,
    TEMP_DOWNLOAD_DIRECTORY, CMD_HELP, LOGS,
)
from userbot.events import register
from userbot.modules.upload_download import humanbytes, time_formatter
from userbot.modules.aria import aria2, check_progress_for_dl, check_metadata
# =========================================================== #
#                          STATIC                             #
# =========================================================== #
GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.metadata"
]
REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
# =========================================================== #
#      STATIC CASE FOR G_DRIVE_FOLDER_ID IF VALUE IS URL      #
# =========================================================== #
__ = G_DRIVE_FOLDER_ID
if __ is not None:
    if "uc?id=" in G_DRIVE_FOLDER_ID:
        LOGS.info(
            "G_DRIVE_FOLDER_ID is not a valid folderURL...")
        G_DRIVE_FOLDER_ID = None
    try:
        G_DRIVE_FOLDER_ID = __.split("folders/")[1]
    except IndexError:
        try:
            G_DRIVE_FOLDER_ID = __.split("open?id=")[1]
        except IndexError:
            try:
                if "/view" in __:
                    G_DRIVE_FOLDER_ID = __.split("/")[-2]
            except IndexError:
                try:
                    G_DRIVE_FOLDER_ID = __.split(
                                      "folderview?id=")[1]
                except IndexError:
                    if any(map(str.isdigit, __)):
                        _1 = True
                    else:
                        _1 = False
                    if "-" in __ or "_" in __:
                        _2 = True
                    else:
                        _2 = False
                    if True in [_1 or _2]:
                        pass
                    else:
                        LOGS.info(
                           "G_DRIVE_FOLDER_ID not valid...")
# =========================================================== #
#                                                             #
# =========================================================== #


async def progress(current, total, event, start, type_of_ps, file_name=None):
    """Generic progress_callback for uploads and downloads."""
    now = time.time()
    diff = now - start
    if round(diff % 10.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000
        estimated_total_time = elapsed_time + time_to_completion
        progress_str = "`Downloading...` | [{0}{1}] `{2}%`\n".format(
            ''.join(["#" for i in range(math.floor(percentage / 10))]),
            ''.join(["**-**" for i in range(10 - math.floor(percentage / 10))]),
            round(percentage, 2))
        tmp = (progress_str + "\n" +
               f"{humanbytes(current)} of {humanbytes(total)}\n"
               f"ETA: {time_formatter(estimated_total_time)}"
               )
        if file_name:
            await event.edit(f"{type_of_ps}\n\n"
                             f" • `Name   :`\n    `{file_name}`"
                             f" • `Status :`\n    {tmp}")
        else:
            await event.edit(f"{type_of_ps}\n\n"
                             f" • `Status :`\n    {tmp}")


@register(pattern="^.gdauth(?: |$)", outgoing=True)
async def generate_credentials(gdrive):
    """ - Only generate once for long run - """
    if G_DRIVE_AUTH_TOKEN_DATA is not None:
        await gdrive.edit("`You already authorized token...`")
        await asyncio.sleep(1.5)
        return await gdrive.delete()
    """ - Generate credentials - """
    if G_DRIVE_DATA is not None:
        configs = json.loads(G_DRIVE_DATA)
    else:
        """ - Only for old user - """
        configs = {
            "installed": {
                "client_id": G_DRIVE_CLIENT_ID,
                "client_secret": G_DRIVE_CLIENT_SECRET,
                "auth_uri": GOOGLE_AUTH_URI,
                "token_uri": GOOGLE_TOKEN_URI,
            }
        }
    await gdrive.edit("`Creating credentials...`")
    flow = InstalledAppFlow.from_client_config(
         configs, SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
                access_type='offline', prompt='consent')
    msg = await gdrive.respond(
        "`Go to your BOTLOG group to authenticate token...`"
        )
    async with gdrive.client.conversation(BOTLOG_CHATID) as conv:
        url_msg = await conv.send_message(
                      "Please go to this URL:\n"
                      f"{auth_url}\nauthorize then reply the code"
                  )
        r = conv.wait_event(
          events.NewMessage(outgoing=True, chats=BOTLOG_CHATID))
        r = await r
        code = r.message.message.strip()
        flow.fetch_token(code=code)
        creds = flow.credentials
        await asyncio.sleep(3.5)
        await gdrive.client.delete_messages(gdrive.chat_id, msg.id)
        await gdrive.client.delete_messages(BOTLOG_CHATID, url_msg.id)
        await gdrive.client.delete_messages(BOTLOG_CHATID, r.id)
        """ - Unpack credential objects into strings - """
        creds = base64.b64encode(pickle.dumps(creds)).decode()
    if HEROKU_API_KEY is None or HEROKU_APP_NAME is None:
        await gdrive.edit(
            "**HEROKU_APP_NAME** `and` **HEROKU_API_KEY**\n"
            "`is empty please setup first...`"
        )
        await asyncio.sleep(1.5)
        gdrive.delete()
    else:
        await gdrive.edit("`Credentials created...`")
        heroku = heroku3.from_key(HEROKU_API_KEY)
        heroku_configvars = heroku.app(HEROKU_APP_NAME).config()
        await gdrive.respond("`Restarting in 3s to initialize token...`")
        await asyncio.sleep(3)
        await gdrive.delete()
        heroku_configvars["G_DRIVE_AUTH_TOKEN_DATA"] = creds
    return


async def create_app(gdrive):
    """ - Create google drive service app - """
    creds = None
    if G_DRIVE_AUTH_TOKEN_DATA is not None:
        """ - Repack credential objects from strings - """
        creds = pickle.loads(
              base64.b64decode(G_DRIVE_AUTH_TOKEN_DATA.encode()))
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            await gdrive.edit("`Refreshing credentials...`")
            """ - Refresh credentials - """
            creds.refresh(Request())
        else:
            return await gdrive.edit(
                "`Credentials is empty, please generate it...`")
    service = build('drive', 'v3', credentials=creds, cache_discovery=False)
    return service


async def get_raw_name(file_path):
    """ - Get file_name from file_path - """
    return file_path.split("/")[-1]


async def get_mimeType(name):
    """ - Check mimeType given file - """
    mimeType = guess_type(name)[0]
    if not mimeType:
        mimeType = 'text/plain'
    return mimeType


async def download(gdrive, service, uri=None):
    """ - Download files to local then upload - """
    if not isdir(TEMP_DOWNLOAD_DIRECTORY):
        os.makedirs(TEMP_DOWNLOAD_DIRECTORY)
        required_file_name = None
    if uri:
        try:
            if uri.endswith(".torrent"):
                pass
        except AttributeError:
            torrent = False
        else:
            torrent = True
        try:
            if torrent is True:
                downloads = aria2.add_torrent(uri,
                                              uris=None,
                                              options=None,
                                              position=None)
            else:
                downloads = aria2.add_uris(uri, options=None, position=None)
        except Exception as e:
            return await gdrive.edit(
                "`[FILE - ERROR]`\n\n"
                " • `Status :` **FAILED**\n"
                " • `Reason :` Download failed.\n"
                f"    `{str(e)}`"
            )
        gid = downloads.gid
        await check_progress_for_dl(gid=gid, event=gdrive, previous=None)
        File = aria2.get_download(gid)
        if File.followed_by_ids:
            new_gid = await check_metadata(gid)
            await check_progress_for_dl(gid=new_gid,
                                        event=gdrive, previous=None)
        for root, dirs, files in os.walk('.'):
            for entry in files:
                if File.name == entry:
                    required_file_name = join(root, entry)
    else:
        try:
            current_time = time.time()
            downloaded_file_name = await gdrive.client.download_media(
                await gdrive.get_reply_message(),
                TEMP_DOWNLOAD_DIRECTORY,
                progress_callback=lambda d, t: asyncio.get_event_loop(
                ).create_task(progress(d, t, gdrive, current_time,
                                       "`[FILE - DOWNLOAD]`")))
        except Exception as e:
            await gdrive.edit(str(e))
        else:
            required_file_name = downloaded_file_name
    try:
        file_name = await get_raw_name(required_file_name)
    except AttributeError:
        return await gdrive.edit(
            "`[ENTRY - ERROR]`\n\n"
            " • `Status :` **BAD**\n"
            " • `Reason :` Replied entry is not media/file it's a messages."
        )
    mimeType = await get_mimeType(required_file_name)
    try:
        result = await upload(gdrive, service, required_file_name,
                              file_name, mimeType)
        return await gdrive.edit(
            "`[FILE - DOWNLOAD]`\n\n"
            f" • `Name     :`\n    `{file_name}`\n"
            " • `Status   :` **OK**\n"
            f" • `URL      :`\n    [{file_name}]({result[0]})\n"
            f" • `Download :`\n    [{file_name}]({result[1]})"
        )
    except Exception as e:
        return await gdrive.edit(
            "`[FILE - ERROR]`\n\n"
            f" • `Name   :`\n    `{file_name}`\n"
            " • `Status :` **FAILED**\n"
            " • `Reason :` failed to upload.\n"
            f"    `{str(e)}`"
        )
    return


async def download_gdrive(gdrive, service, uri):
    """ - remove drivesdk and export=download from link - """
    if not isdir(TEMP_DOWNLOAD_DIRECTORY):
        os.mkdir(TEMP_DOWNLOAD_DIRECTORY)
    if "&export=download" in uri:
        uri = uri.split("&export=download")[0]
    elif "file/d/" in uri and "/view" in uri:
        uri = uri.split("?usp=drivesdk")[0]
    try:
        file_Id = uri.split("uc?id=")[1]
    except IndexError:
        try:
            file_Id = uri.split("open?id=")[1]
        except IndexError:
            try:
                if "/view" in uri:
                    file_Id = uri.split("/")[-2]
            except IndexError:
                """ - if error parse in url, assume given value is Id - """
                file_Id = uri
    file = service.files().get(fileId=file_Id,
                               fields='name, mimeType').execute()
    file_name = file.get('name')
    mimeType = file.get('mimeType')
    if mimeType == 'application/vnd.google-apps.folder':
        return await gdrive.edit("`Aborting, folder download not support`")
    file_path = TEMP_DOWNLOAD_DIRECTORY + file_name
    request = service.files().get_media(fileId=file_Id)
    with io.FileIO(file_path, 'wb') as df:
        downloader = MediaIoBaseDownload(df, request)
        complete = False
        current_time = time.time()
        display_message = None
        while complete is False:
            status, complete = downloader.next_chunk()
            if status:
                file_size = status.total_size
                diff = time.time() - current_time
                downloaded = status.resumable_progress
                percentage = downloaded / file_size * 100
                speed = round(downloaded / diff, 2)
                eta = round((file_size - downloaded) / speed)
                prog_str = "`Downloading...` | [{0}{1}] `{2}%`".format(
                    "".join(["#" for i in range(math.floor(percentage / 5))]),
                    "".join(["**-**"
                             for i in range(20 - math.floor(percentage / 5))]),
                    round(percentage, 2))
                current_message = (
                    "`[FILE - DOWNLOAD]`\n\n"
                    f"`Name   :`\n`{file_name}`\n\n"
                    "`Status :`\n"
                    f"{prog_str}\n"
                    f"`{humanbytes(downloaded)} of {humanbytes(file_size)} "
                    f"@ {humanbytes(speed)}`\n"
                    f"`ETA` -> {time_formatter(eta)}"
                )
                if display_message != current_message:
                    try:
                        await gdrive.edit(current_message)
                        display_message = current_message
                    except Exception:
                        pass
        await gdrive.edit(
            "`[FILE - DOWNLOAD]`\n\n"
            f"`Name   :`\n`{file_name}`\n\n"
            f"`Path   :` `{file_path}`\n"
            "`Status :` **OK**\n"
            "`Reason :` Successfully downloaded..."
        )
        msg = await gdrive.respond("`Answer the question in your BOTLOG group`")
    async with gdrive.client.conversation(BOTLOG_CHATID) as conv:
        ask = await conv.send_message("`Proceed with mirroring? [y/N]`")
        try:
            r = conv.wait_event(
              events.NewMessage(outgoing=True, chats=BOTLOG_CHATID))
            r = await r
        except Exception:
            ans = 'N'
        else:
            ans = r.message.message.strip()
            await gdrive.client.delete_messages(BOTLOG_CHATID, r.id)
        await gdrive.client.delete_messages(gdrive.chat_id, msg.id)
        await gdrive.client.delete_messages(BOTLOG_CHATID, ask.id)
    if ans.capitalize() == 'N':
        return
    elif ans.capitalize() == "Y":
        result = await upload(gdrive, service, file_path, file_name, mimeType)
        await gdrive.respond(
            "`[FILE - UPLOAD]`\n\n"
            f" • `Name     :` `{file_name}`\n"
            " • `Status   :` **OK**\n"
            f" • `URL      :` [{file_name}]({result[0]})\n"
            f" • `Download :` [{file_name}]({result[1]})"
        )
        return await gdrive.delete()
    else:
        return await gdrive.client.send_message(
            BOTLOG_CHATID,
            "`Invalid answer type [Y/N] only...`"
        )


async def create_dir(service, folder_name):
    metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
    }
    permission = {
        "role": "reader",
        "type": "anyone",
        "allowFileDiscovery": True,
        "value": None,
    }
    try:
        if parent_Id is not None:
            pass
    except NameError:
        """ - Fallback to G_DRIVE_FOLDER_ID else root dir - """
        if G_DRIVE_FOLDER_ID is not None:
            metadata['parents'] = [G_DRIVE_FOLDER_ID]
    else:
        """ - Override G_DRIVE_FOLDER_ID because parent_Id not empty - """
        metadata['parents'] = [parent_Id]
    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder.get('id')
    try:
        service.permissions().create(fileId=folder_id, body=permission
                                     ).execute()
    except Exception:
        pass
    return folder_id


async def upload(gdrive, service, file_path, file_name, mimeType):
    await gdrive.edit("`Processing upload...`")
    body = {
        "name": file_name,
        "description": "Uploaded from Telegram using `sql-extended`.",
        "mimeType": mimeType,
    }
    try:
        if parent_Id is not None:
            pass
    except NameError:
        """ - Fallback to G_DRIVE_FOLDER_ID else root dir - """
        if G_DRIVE_FOLDER_ID is not None:
            body['parents'] = [G_DRIVE_FOLDER_ID]
    else:
        """ - Override G_DRIVE_FOLDER_ID because parent_Id not empty - """
        body['parents'] = [parent_Id]
    permission = {
        "role": "reader",
        "type": "anyone",
        "allowFileDiscovery": True,
        "value": None,
    }
    media_body = MediaFileUpload(
        file_path,
        mimetype=mimeType,
        resumable=True
    )
    """ - Start upload process - """
    response = None
    display_message = None
    file = service.files().create(body=body, media_body=media_body,
                                  fields="id, webContentLink, webViewLink")
    while response is None:
        status, response = file.next_chunk()
        await asyncio.sleep(0.3)
        if status:
            percentage = int(status.progress() * 100)
            prog_str = "`Uploading...` | [{0}{1}] `{2}%`".format(
                "".join(["**#**" for i in range(math.floor(percentage / 10))]),
                "".join(["**-**"
                         for i in range(10 - math.floor(percentage / 10))]),
                round(percentage, 2))
            current_message = (
                "`[FILE - UPLOAD]`\n\n"
                f" • `Name   :`\n    `{file_name}`\n"
                " • `Status :`\n"
                f"    {prog_str}"
            )
            if display_message != current_message:
                try:
                    await gdrive.edit(current_message)
                    display_message = current_message
                except Exception:
                    pass
    file_id = response.get("id")
    viewURL = response.get("webViewLink")
    downloadURL = response.get("webContentLink")
    """ - Change permission - """
    try:
        service.permissions().create(fileId=file_id, body=permission).execute()
    except HttpError as e:
        return await gdrive.edit("`" + str(e) + "`")
    return viewURL, downloadURL


@register(pattern="^.gdf (mkdir|rm|chck)(.*)", outgoing=True)
async def google_drive_managers(gdrive):
    """ - Google Drive folder/file management - """
    await gdrive.edit("`Sending information...`")
    service = await create_app(gdrive)
    f_name = gdrive.pattern_match.group(2).strip()
    exe = gdrive.pattern_match.group(1)
    """ - Only if given value are mkdir - """
    metadata = {
        'name': f_name,
        'mimeType': 'application/vnd.google-apps.folder',
    }
    try:
        if parent_Id is not None:
            pass
    except NameError:
        """ - Fallback to G_DRIVE_FOLDER_ID else to root dir - """
        if G_DRIVE_FOLDER_ID is not None:
            metadata['parents'] = [G_DRIVE_FOLDER_ID]
    else:
        """ - Override G_DRIVE_FOLDER_ID because parent_Id not empty - """
        metadata['parents'] = [parent_Id]
    permission = {
        "role": "reader",
        "type": "anyone",
        "allowFileDiscovery": True,
        "value": None,
    }
    page_token = None
    result = service.files().list(
        q=f'name="{f_name}"',
        spaces='drive',
        fields=(
            'nextPageToken, files(parents, name, id, '
            'mimeType, webViewLink, webContentLink, description)'
        ),
        pageToken=page_token
    ).execute()
    if exe == "mkdir":
        """ - Create a directory, abort if exist when parent not given - """
        status = "[FOLDER - EXIST]"
        try:
            folder = result.get('files', [])[0]
        except IndexError:
            folder = service.files().create(
                   body=metadata,
                   fields="id, webViewLink"
             ).execute()
            status = status.replace("EXIST]", "CREATED]")
        folder_id = folder.get('id')
        webViewURL = folder.get('webViewLink')
        if "CREATED" in status:
            """ - Change permission - """
            try:
                service.permissions().create(
                   fileId=folder_id, body=permission).execute()
            except HttpError as e:
                return await gdrive.edit("`" + str(e) + "`")
        await gdrive.edit(
            f"`{status}`\n\n"
            f" • `Name :`\n    `{f_name}`\n"
            f" • `ID   :` `{folder_id}`\n"
            f" • `URL  :`\n    [Open]({webViewURL})"
        )
    elif exe == "rm":
        """ - Permanently delete, skipping the trash - """
        try:
            """ - Try if given value is a name not a folderId/fileId - """
            f = result.get('files', [])[0]
            f_id = f.get('id')
        except IndexError:
            """ - If failed assumming value is folderId/fileId - """
            f_id = f_name
            try:
                f = service.files().get(fileId=f_id,
                                        fields="name, mimeType").execute()
            except Exception as e:
                return await gdrive.edit(
                    f"`[FILE/FOLDER - ERROR]`\n\n"
                    f" • `Status :` `{str(e)}`"
                )
        name = f.get('name')
        mimeType = f.get('mimeType')
        if mimeType == 'application/vnd.google-apps.folder':
            status = "[FOLDER - DELETE]"
        else:
            status = "[FILE - DELETE]"
        try:
            service.files().delete(fileId=f_id).execute()
        except HttpError as e:
            status.replace("DELETE]", "ERROR]")
            return await gdrive.edit(
                f"`{status}`\n\n"
                f" • `Status :` `{str(e)}`"
            )
        else:
            await gdrive.edit(
                    f"`{status}`\n\n"
                    f" • `Name   :`\n    `{name}`\n"
                    " • `Status :` `OK`"
            )
    elif exe == "chck":
        """ - Check file/folder if exists - """
        try:
            f = result.get('files', [])[0]
        except IndexError:
            """ - If failed assumming value is folderId/fileId - """
            f_id = f_name
            try:
                f = service.files().get(
                       fileId=f_id,
                       fields="name, id, mimeType, "
                              "webViewLink, webContentLink, description"
                ).execute()
            except Exception as e:
                return await gdrive.edit(
                    "`[FILE/FOLDER - ERROR]`\n\n"
                    " • `Status :` **BAD**\n"
                    f" • `Reason :` `{str(e)}`"
                )
        """ - If exists parse file/folder information - """
        f_name = f.get('name')  # override input value
        f_id = f.get('id')
        mimeType = f.get('mimeType')
        webViewLink = f.get('webViewLink')
        downloadURL = f.get('webContentLink')
        description = f.get('description')
        if mimeType == "application/vnd.google-apps.folder":
            status = "[FOLDER - EXIST]"
        else:
            status = "[FILE - EXIST]"
        msg = (
            f"`{status}`\n\n"
            f" • `Name     :`\n    `{f_name}`\n"
            f" • `ID       :` `{f_id}`\n"
            f" • `URL      :`\n    [Open]({webViewLink})\n"
        )
        if mimeType != "application/vnd.google-apps.folder":
            msg += f" • `Download :`\n    [{f_name}]({downloadURL})\n"
        if description:
            msg += f" • `About    :`\n    `{description}`"
        await gdrive.edit(msg)
    page_token = result.get('nextPageToken', None)
    return


@register(pattern="^.gd(?: |$)(.*)", outgoing=True)
async def google_drive(gdrive):
    """ - Parsing all google drive function - """
    value = gdrive.pattern_match.group(1)
    file_path = None
    uri = None
    if not value and not gdrive.reply_to_msg_id:
        return
    elif value and gdrive.reply_to_msg_id:
        return await gdrive.edit(
            "`[UNKNOWN - ERROR]`\n\n"
            " • `Status :` **FAILED**\n"
            f" • `Reason :` Confused to upload file or the replied message/media."
        )
    if isfile(value):
        file_path = value
        if file_path.endswith(".torrent"):
            uri = file_path
            file_path = None
    elif isdir(value):
        return await gdrive.edit(
            "`[FOLDER - ERROR]`\n\n"
            " • `Status :` **BAD**\n"
            " • `Reason :` Folder upload not supported."
        )
    else:
        if re.findall(r'\bhttps?://.*\.\S+', value) or "magnet:?" in value:
            try:
                uri = re.findall(r'\bhttps?://drive\.google\.com\S+', value)[0]
            except IndexError:
                uri = value.split()
            else:
                """ - Link is google drive fallback to download - """
                return await download_gdrive(gdrive, service, uri)
        else:
            if any(map(str.isdigit, value)):
                one = True
            else:
                one = False
            if "-" in value or "_" in value:
                two = True
            else:
                two = False
            if True in [one or two]:
                return await download_gdrive(gdrive, service, value)
        if not uri and not gdrive.reply_to_msg_id:
            return await gdrive.edit(
                "`[VALUE - ERROR]`\n\n"
                " • `Status :` **BAD**\n"
                " • `Reason :` given value is not URL nor file path."
            )
    service = await create_app(gdrive)
    if uri and not gdrive.reply_to_msg_id:
        return await download(gdrive, service, uri)
    if not file_path and gdrive.reply_to_msg_id:
        return await download(gdrive, service)
    mimeType = await get_mimeType(file_path)
    file_name = await get_raw_name(file_path)
    viewURL, downloadURL = await upload(
                         gdrive, service, file_path, file_name, mimeType)
    if viewURL and downloadURL:
        await gdrive.edit(
            "`[FILE - UPLOAD]`\n\n"
            f" • `Name     :`\n    `{file_name}`\n"
            " • `Status   :` **OK**\n"
            f" • `URL      :`\n    [{file_name}]({viewURL})\n"
            f" • `Download :`\n    [{file_name}]({downloadURL})"
        )
    return


@register(pattern="^.gdfset (put|rm)(?: |$)(.*)", outgoing=True)
async def set_upload_folder(gdrive):
    """ - Set parents dir for upload/check/makedir/remove - """
    await gdrive.edit("`Sending information...`")
    global parent_Id
    exe = gdrive.pattern_match.group(1)
    if exe == "rm":
        if G_DRIVE_FOLDER_ID is not None:
            parent_Id = G_DRIVE_FOLDER_ID
            return await gdrive.edit(
                "`[FOLDER - SET]`\n\n"
                " • `Status :` **OK**\n"
                " • `Reason :` upload will use `G_DRIVE_FOLDER_ID`,\n"
                "    as parentId for next."
            )
        else:
            parent_Id = None
            return await gdrive.edit(
                "`[FOLDER - SET]`\n\n"
                " • `Status :` **OK**\n"
                " • `Reason :` `G_DRIVE_FOLDER_ID` is empty,\n"
                "    upload will use root dir.")
    inp = gdrive.pattern_match.group(2)
    if not inp:
        return await gdrive.edit(">`.gdfset put <folderURL/folderID>`")
    """ - Value for .gdfset (put|rm) can be folderId or folder link - """
    try:
        ext_id = re.findall(r'\bhttps?://drive\.google\.com\S+', inp)[0]
    except IndexError:
        """ - if given value isn't folderURL assume it's an Id - """
        if any(map(str.isdigit, inp)):
            c1 = True
        else:
            c1 = False
        if "-" in inp or "_" in inp:
            c2 = True
        else:
            c2 = False
        if True in [c1 or c2]:
            parent_Id = inp
            await gdrive.edit(
                "`[PARENT - FOLDER]`\n\n"
                " • `Status :` **OK**\n"
                " • `Reason :` Successfully changed."
            )
        parent_Id = inp
    else:
        if "uc?id=" in ext_id:
            return await gdrive.edit(
                "`[URL - ERROR]`\n\n"
                " • `Status :` **BAD**\n"
                " • `Reason :` Not a valid folderURL."
            )
        try:
            parent_Id = ext_id.split("folders/")[1]
        except IndexError:
            """ - Try catch again if URL open?id= - """
            try:
                parent_Id = ext_id.split("open?id=")[1]
            except IndexError:
                try:
                    if "/view" in ext_id:
                        parent_Id = ext_id.split("/")[-2]
                except IndexError:
                    """ - Last attemp to catch - """
                    try:
                        parent_Id = ext_id.split("folderview?id=")[1]
                    except IndexError:
                        return await gdrive.edit(
                            "`[URL - ERROR]`\n\n"
                            " • `Status :` **BAD**\n"
                            " • `Reason :` Not a valid folderURL or empty."
                        )
        await gdrive.edit(
                "`[PARENT - FOLDER]`\n\n"
                " • `Status :` **OK**\n"
                " • `Reason :` Successfully changed."
        )
    return parent_Id


CMD_HELP.update({
    "gdrive":
    ".gd"
    "\nUsage: Upload file from local or uri into google drive."
    "\n\n.gdf mkdir <folder name>"
    ">`.gdauth`"
    "\nUsage: generate token to enable all cmd google drive service."
    "\nThis only need to run once in life time."
    "\n\n>.`gd`"
    "\nUsage: Upload file from local or uri/url into google drive."
    "\n\n>`.gdf mkdir <folder name>`"
    "\nUsage: create google drive folder."
    "\n\n.gdf chck <folder/file|name/id>"
    "\nUsage: check given value is exist or not."
    "\n\n.gdf rm <folder/file|name/id>"
    "\nUsage: delete a file/folder, and can't be undone"
    "\nThis method skipping file trash, so be caution..."
    "\n\n.gdfset put <folderURL/folderID>"
    "\nUsage: change upload directory."
    "\n\n.gdfset rm"
    "\nUsage: remove set parentId from\n.gdfset put <value>"
    "to **G_DRIVE_FOLDER_ID** and if empty upload will go to root."
    "\n\n>`.gdfset rm`"
    "\nUsage: remove set parentId from cmd\n>`.gdfset put` "
    "into **G_DRIVE_FOLDER_ID** and if empty upload will go to root."
})
