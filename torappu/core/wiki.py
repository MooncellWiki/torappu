import json
import time
import traceback
from urllib.parse import quote

import httpx
from tenacity import retry, stop_after_attempt


class Wiki:
    async def close(self):
        return await self.client.aclose()

    async def __init__(self, api_url, username, password, mode="product"):
        self.api_url = api_url
        self.mode = mode
        self.client = httpx.AsyncClient()

        lgtoken = await self.client.get(
            api_url,
            params={
                "format": "json",
                "action": "query",
                "meta": "tokens",
                "type": "login",
            },
        )
        res = await self.client.post(
            api_url,
            data={
                "format": "json",
                "action": "login",
                "lgname": username,
                "lgpassword": password,
                "lgtoken": lgtoken.json()["query"]["tokens"]["logintoken"],
            },
        )
        if res.json()["login"]["result"] != "Success":
            raise RuntimeError(res.json()["login"]["reason"])

    @retry(stop=stop_after_attempt(3))
    async def edit(
        self,
        title=None,
        pageid=None,
        section=None,
        sectiontitle=None,
        text=None,
        summary=None,
        minor=None,
        bot=True,
        createonly=None,
        nocreate=None,
        prependtext=None,
        appendtext=None,
        redirect=None,
        contentformat=None,
        contentmodel=None,
    ):
        """
        :param title: 要编辑的页面标题。不能与pageid一起使用。
        :param pageid:要编辑的页面的页面 ID。不能与title一起使用。
        :param section:段落数。0用于首段，new用于新的段落。NOTICE:会覆盖==xx==的部分
        :param sectiontitle:新段落的标题。
        :param text:页面内容。
        :param summary:编辑摘要。当section=new且未设置sectiontitle时，还包括小节标题。
        :param minor:小编辑。
        :param bot:机器人编辑。
        :param createonly:不要编辑页面，如果已经存在。
        :param nocreate:如果该页面不存在，则抛出一个错误。
        :param prependtext:将该文本添加到该页面的开始。覆盖text。
        :param appendtext:将该文本添加到该页面的结尾。覆盖text。
        :param redirect:自动解决重定向。
        :param contentformat:用于输入文本的内容序列化格式。application/json、text/plain、text/css、text/x-wiki、text/javascript
        :param contentmodel:新内容的内容模型。GadgetDefinition、Scribunto、sanitized-css、flow-board、wikitext、javascript、json、css、text、smw/schema
        :type minor: bool
        :type bot: bool
        :type createonly:bool
        :type nocreate:bool
        :type redirect:bool
        :return:post response
        """
        args = locals().copy()
        args.pop("self")
        if self.mode != "product":
            print("\n" + str(args) + "\n")
            return
        boolargs = {"minor", "createonly", "nocreate", "redirect", "bot"}
        token = await self.client.get(
            self.api_url,
            params={
                "format": "json",
                "action": "query",
                "meta": "tokens",
            },
        )
        post_data = {
            "format": "json",
            "action": "edit",
            "token": token.json()["query"]["tokens"]["csrftoken"],
        }
        for key in args:
            if args[key] is not None:
                if key in boolargs and args[key]:
                    post_data[key] = "1"
                else:
                    post_data[key] = args[key]
        # time.sleep(1)
        return await self.client.post(self.api_url, data=post_data)

    @retry(stop=stop_after_attempt(3))
    async def read(self, title):
        """
        :param title: 名称空间:页面名
        :return: wikitext
        """
        res = await self.client.post(
            self.api_url,
            data={
                "format": "json",
                "action": "query",
                "titles": title,
                "prop": "revisions",
                "rvprop": "content",
            },
        )
        ret = json.loads(res.text)["query"]["pages"]
        for k in ret:
            ret = ret[k]
            break
        return ret["revisions"][0]["*"]

    @retry(stop=stop_after_attempt(3))
    async def category(self, category):
        res = await self.client.post(
            self.api_url,
            data={
                "format": "json",
                "action": "query",
                "list": "categorymembers",
                "cmtitle": category,
                "cmlimit": 3000,
            },
        )
        ret = res.json()["query"]["categorymembers"]
        return [page["title"] for page in ret]

    @retry(stop=stop_after_attempt(3))
    async def protect(
        self, title=None, pageid=None, protections=None, reason=None, cascade=None
    ):
        """
        :param title:要（解除）保护的页面标题。不能与pageid一起使用。
        :param pageid:要（解除）保护的页面ID。不能与title一起使用。
        :param protections:保护等级列表，格式：action=level（例如edit=sysop）。等级all意味着任何人都可以执行操作，也就是说没有限制。
        注意：未列出的操作将移除限制。
        :param reason:（解除）保护的原因。
        :param cascade:启用连锁保护（也就是保护包含于此页面的页面）。如果所有提供的保护等级不支持连锁，就将其忽略。
        :type cascade:bool
        :return:
        """
        args = locals().copy()
        args.pop("self")
        if self.mode != "product":
            print("\n" + "\n" + str(args) + "\n")
            return
        token = await self.client.get(
            self.api_url,
            params={
                "format": "json",
                "action": "query",
                "meta": "tokens",
            },
        )
        post_data = {
            "format": "json",
            "action": "protect",
            "token": token.json()["query"]["tokens"]["csrftoken"],
            "expiry": "infinite",
        }
        for key in args:
            if not args[key] is None:
                if key == "cascade" and args[key]:
                    post_data[key] = "1"
                else:
                    post_data[key] = args[key]
        return await self.client.post(self.api_url, data=post_data)

    @retry(stop=stop_after_attempt(3))
    async def upload(self, filepath, filename, comment=None, text=None):
        """
        :param filepath:文件路径
        :param filename:目标文件名
        :param comment:上传注释。如果没有指定text，那么它也被用于新文件的初始页面文本。
        :param text:用于新文件的初始页面文本。
        :return:
        """
        args = locals().copy()
        args.pop("self")
        token = await self.client.get(
            self.api_url,
            params={
                "format": "json",
                "action": "query",
                "meta": "tokens",
            },
        )
        upload_data = {
            "format": "json",
            "action": "upload",
            "filename": filename,
            "ignorewarnings": "1",
            "token": token.json()["query"]["tokens"]["csrftoken"],
        }
        header = {
            "Content-Disposition": 'form-data; name="data"; filename="%s"'
            % quote(filename)
        }
        for key in args:
            if not args[key] is None:
                upload_data[key] = args[key]
        r = await self.client.post(
            self.api_url,
            data=upload_data,
            files={"file": (quote(filename), open(filepath, "rb"))},
            headers=header,
        )
        return r
