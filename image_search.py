"""Fetch one actual public image, with bounded downloads and local validation."""
import hashlib
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API='https://commons.wikimedia.org/w/api.php'
HOSTS={'commons.wikimedia.org','upload.wikimedia.org','thumb.wikimedia.org'}
USER_AGENT='WeChatPhotoBot/1.0 (personal photo lookup)'
CACHE=Path(__file__).with_name('found_images')
MAX_BYTES=12*1024*1024


def _public_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Unsupported public image source')
    return url


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        _public_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


def _fetch(url,deadline,maximum):
    remaining=deadline-time.monotonic()
    if remaining<=0:
        raise TimeoutError('Image lookup deadline')
    request=urllib.request.Request(_public_url(url),headers={'User-Agent':USER_AGENT})
    with urllib.request.build_opener(_Redirects()).open(request,timeout=min(8,remaining)) as response:
        _public_url(response.url)
        content=response.read(maximum+1)
        if len(content)>maximum:
            raise ValueError('Image response exceeds size limit')
        return content


def _plain(value):
    return html.unescape(re.sub(r'<[^>]*>','',str(value or ''))).strip()[:250]


def find_image(query,alternate=None):
    queries=list(dict.fromkeys(q.strip() for q in (query,alternate) if isinstance(q,str) and q.strip()))
    if (not queries or any(len(q)>100 or re.search(r'https?://|wxid_|[A-Za-z]:\\|Bearer |sk-[A-Za-z0-9_-]{10,}',q) for q in queries)):
        return {'ok':False,'error':'请提供简短的公开图片主题，不提交网址、账号或秘密。'}
    deadline=time.monotonic()+22
    from PIL import Image
    for phrase in queries[:2]:
        try:
            params=dict(action='query',format='json',generator='search',gsrsearch=phrase+' filetype:bitmap',
                        gsrnamespace=6,gsrlimit=5,prop='imageinfo',iiprop='url|mime|size|extmetadata',
                        iiurlwidth=1600,iiextmetadatafilter='Artist|Credit|LicenseShortName')
            data=json.loads(_fetch(API+'?'+urllib.parse.urlencode(params),deadline,2*1024*1024))
            pages=list(data.get('query',{}).get('pages',{}).values())
            pages.sort(key=lambda item:item.get('index',999))
            for page in pages[:3]:
                info=(page.get('imageinfo') or [{}])[0]
                if info.get('mime') not in ('image/jpeg','image/png'):
                    continue
                url=info.get('thumburl') or info.get('url')
                if not url:
                    continue
                try:
                    payload=_fetch(url,deadline,MAX_BYTES)
                    with Image.open(io.BytesIO(payload)) as image:
                        if image.format not in ('JPEG','PNG') or min(image.size)<128 or image.width*image.height>40_000_000:
                            continue
                        extension='.jpg' if image.format=='JPEG' else '.png'
                        image.verify()
                    key=hashlib.sha256(url.encode()).hexdigest()[:24]
                    CACHE.mkdir(exist_ok=True)
                    path=CACHE/('photo_'+key+extension)
                    path.write_bytes(payload)
                    metadata=info.get('extmetadata') or {}
                    source=dict(title=_plain(page.get('title','')).removeprefix('File:'),
                        source='维基共享资源',source_page=info.get('descriptionurl',''),
                        author=_plain((metadata.get('Artist') or {}).get('value')),
                        license=_plain((metadata.get('LicenseShortName') or {}).get('value')))
                    path.with_suffix('.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf-8')
                    return dict(ok=True,path=str(path.resolve()),**source)
                except Exception:
                    continue
        except Exception as exc:
            print('公开图片检索未完成：',type(exc).__name__,flush=True)
    return {'ok':False,'error':'这次没有找到可下载并确认格式的合适图片，未用文字或表情包冒充。'}
