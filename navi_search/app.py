import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import timedelta
from functools import partial
from typing import List

import pandas as pd
import streamlit as st
from loguru import logger as log
from search_engine_parser import BaiduSearch as _BaiduSearch
from search_engine_parser import DuckDuckGoSearch as _DuckDuckGoSearch
from search_engine_parser import GithubSearch as _GithubSearch
from search_engine_parser import GoogleScholarSearch as _GoogleScholarSearch
from search_engine_parser import GoogleSearch as _GoogleSearch
from search_engine_parser.core.base import SearchItem
from search_engine_parser.core.engines.google import EXTRA_PARAMS
from search_engine_parser.core.engines.youtube import Search as YoutubeSearch
from search_engine_parser.core.exceptions import NoResultsOrTrafficError
from search_engine_parser.core.utils import CacheHandler as _CacheHandler
from search_engine_parser.core.utils import FILEPATH

SEARCH_RESULT_TTL_SECONDS = 120


class ExpiringDict(dict):
    def __init__(self, ttl: int):
        super().__init__()
        self.ttl = ttl

    def __setitem__(self, key, value):
        super().__setitem__(key, (value, time.time()))

    def __getitem__(self, key):
        value, timestamp = super().__getitem__(key)
        if time.time() - timestamp > self.ttl:
            del self[key]
            raise KeyError(key)
        return value

    def __contains__(self, key):
        try:
            value, timestamp = super().__getitem__(key)
            if time.time() - timestamp > self.ttl:
                del self[key]
                return False
            return True
        except KeyError:
            return False


class CacheHandler(_CacheHandler):
    def __init__(self):
        self.cache = os.path.join(".cache", "cache")
        engine_path = os.path.join(FILEPATH, "engines")
        if not os.path.exists(self.cache):
            os.makedirs(self.cache)
        enginelist = os.listdir(engine_path)
        self.engine_cache = {
            i[:-3]: os.path.join(self.cache, i[:-3])
            for i in enginelist
            if i not in ("__init__.py")
        }
        for cache in self.engine_cache.values():
            if not os.path.exists(cache):
                os.makedirs(cache)


class DuckDuckGoSearch(_DuckDuckGoSearch):
    def get_cache_handler(self):
        return CacheHandler()


class GithubSearch(_GithubSearch):
    def get_cache_handler(self):
        return CacheHandler()


class GoogleScholarSearch(_GoogleScholarSearch):
    def get_cache_handler(self):
        return CacheHandler()


class GoogleSearch(_GoogleSearch):
    def get_cache_handler(self):
        return CacheHandler()

    def get_params(self, query=None, offset=None, page=None, **kwargs):
        params = {}
        params["start"] = (page - 1) * 10
        params["q"] = query
        params["gbv"] = 1
        if kwargs.get("num"):
            params["num"] = kwargs["num"]
        for param in EXTRA_PARAMS:
            if kwargs.get(param):
                params[param] = kwargs[param]
        return params


class BaiduSearch(_BaiduSearch):
    def get_cache_handler(self):
        return CacheHandler()

    def get_params(self, query=None, page=None, offset=None, **kwargs):
        params = {}
        params["wd"] = query
        params["pn"] = (page - 1) * 10
        params["oq"] = query
        if kwargs.get("rn"):
            params["rn"] = kwargs["rn"]
        return params


_search_engines = {
    "Google": GoogleSearch(),
    "DuckDuckGo": DuckDuckGoSearch(),
    "Baidu": BaiduSearch(),
    "Google Scholar": GoogleScholarSearch(),
    "GitHub": GithubSearch(),
    "YouTube": YoutubeSearch(),
}

supported_search_engines = list(_search_engines.keys())


def make_search_url(engine, keyword, **kwargs) -> str:
    url = _search_engines[engine].get_search_url(keyword, **kwargs)
    return url


class SearchRequest:
    def __init__(self, engine: str, keyword: str, page: int = 1, num_results: int = 10):
        self.engine = engine
        self.query_keyword = keyword
        self.page = page
        self.num_param = self.get_num_param(num_results)
        self.search_url = make_search_url(engine, keyword, page=page, **self.num_param)

    def get_num_param(self, num_results):
        if self.engine == "Google":
            num_param = {"num": num_results}
        # elif self.engine == "Baidu":
        #     num_param = {"rn": num_results}
        else:
            num_param = {}
        return num_param

    def __eq__(self, other):
        return self.search_url == other.search_url

    def __hash__(self):
        return hash(self.search_url)


@dataclass()
class SearchResponse:
    search_request: SearchRequest
    results: List[SearchItem] = None
    error_info: str = ""


async def fetch_search_results(
    engine, keyword, page=1, num_results=10
) -> SearchResponse:
    error_msg = ""
    req = SearchRequest(engine, keyword, page, num_results)
    log.info(f"search url: {req.search_url}")
    try:
        search_engine = _search_engines[engine]
        results = await search_engine.async_search(
            keyword, page=page, **req.num_param, cache=False
        )
    except NoResultsOrTrafficError as e:
        results = None
        error_msg = str(e)
        log.error(f"Search error: {e}")
    res = SearchResponse(req, results, error_msg)
    return res


@st.cache_resource(ttl=timedelta(days=1), max_entries=100000)
def search(search_engine, query_keyword, page_num, num_results) -> SearchResponse:
    return asyncio.run(
        fetch_search_results(
            search_engine,
            query_keyword,
            page=page_num,
            num_results=num_results,
        )
    )


def search_preview(search_engine, query_keyword, page_num, num_results):
    if not query_keyword:
        st.toast(":orange-background[请输入关键词进行搜索!]")
        return

    req = SearchRequest(search_engine, query_keyword, page_num, num_results)
    if req in st.session_state.search_results:
        st.toast(f"已经搜索过该关键词，从缓存读取搜索结果，{SEARCH_RESULT_TTL_SECONDS} 秒后过期。")
        return

    res = search(search_engine, query_keyword, page_num, num_results)
    if res.results:
        st.session_state.search_results[res.search_request] = res
    else:
        st.toast(":orange-background[没有查询到结果或者查询失败!]", icon="⚠️")
        if res.error_info:
            st.toast(res.error_info, icon="⚠️")


def search_sidebar_frag():
    with st.sidebar:
        st.image("https://img.icons8.com/clouds/500/search.png", width=100)
        st.subheader(":blue[_Navi Search_]", divider="gray")
        selected_engine = st.selectbox(
            "选择搜索引擎", supported_search_engines, key="engine_selector"
        )
        query_keyword = st.text_input("请输入搜索关键词", value="脑洞部长", key="keyword_input")
        page_num = st.number_input(
            "分页",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
            help="最多支持搜索 10 页结果",
            key="page_num_input",
        )
        num_results = st.number_input(
            "每页搜索结果数量",
            min_value=1,
            max_value=100,
            value=10,
            step=10,
            help="只有 Google 支持更改每页结果数量，最大 100",
            key="num_results_input",
        )
        st.session_state.selected_engine = selected_engine
        st.session_state.query_keyword = query_keyword
        st.session_state.page_num = page_num
        st.session_state.num_results = num_results
        st.button(
            "搜索",
            use_container_width=True,
            type="primary",
            on_click=partial(
                search_preview,
                selected_engine,
                query_keyword,
                page_num,
                num_results,
            ),
        )


def welcome_frag():
    st.header("欢迎使用 :blue[_Navi Search_] 下载搜索结果", divider="rainbow")
    st.write(
        "支持从 _Google_、_DuckDuckGo_、_Baidu_、_Google Scholar_、_GitHub_、_YouTube_ 搜索。"
    )


@st.experimental_fragment
def preview_frag():
    preview_cntr = st.container()
    req = SearchRequest(
        st.session_state.selected_engine,
        st.session_state.query_keyword,
        st.session_state.page_num,
        st.session_state.num_results,
    )
    if st.session_state.search_results.get(req):
        results_df = pd.DataFrame(
            [dict(item) for item in st.session_state.search_results[req].results]
        )
        height = 410
        rows = len(results_df)
        if rows > 20:
            height = 810
        preview_cntr.markdown("**搜索结果预览**")
        table_tab, link_tab, json_tab, csv_tab = preview_cntr.tabs(
            ["表格", "Markdown 链接", "JSON", "CSV"]
        )
        with table_tab:
            st.dataframe(
                results_df,
                column_config={
                    "links": st.column_config.LinkColumn("links"),
                },
                hide_index=False,
                height=height,
            )
        with link_tab:
            results_df["md_links"] = (
                "[" + results_df["titles"] + "](" + results_df["links"] + ")"
            )
            st.code("\n".join(results_df["md_links"].to_list()), language="markdown")
        with json_tab:
            st.code(
                json.dumps(
                    results_df.to_dict(orient="records"),
                    indent=2,
                    ensure_ascii=False,
                ),
                language="json",
            )
        with csv_tab:
            st.code(results_df.to_csv(index=False), language="text")
    else:
        preview_cntr.info("请搜索关键词...")


def main():
    if "search_results" not in st.session_state:
        st.session_state.search_results = ExpiringDict(ttl=SEARCH_RESULT_TTL_SECONDS)
    st.set_page_config(page_title="Navi Search", layout="wide")
    search_sidebar_frag()
    welcome_frag()
    preview_frag()


if __name__ == "__main__":
    main()
