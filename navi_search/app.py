import asyncio
from functools import partial
from typing import List, Union, Tuple

import pandas as pd
import streamlit as st
from loguru import logger as log
from search_engine_parser import BaiduSearch as _BaiduSearch
from search_engine_parser import (
    DuckDuckGoSearch,
    GoogleScholarSearch,
    GithubSearch,
)
from search_engine_parser import GoogleSearch as _GoogleSearch
from search_engine_parser.core.base import SearchItem
from search_engine_parser.core.engines.google import EXTRA_PARAMS
from search_engine_parser.core.engines.youtube import Search as YoutubeSearch
from search_engine_parser.core.exceptions import NoResultsOrTrafficError


class GoogleSearch(_GoogleSearch):
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
    def get_params(self, query=None, page=None, offset=None, **kwargs):
        params = {}
        params["wd"] = query
        params["pn"] = (page - 1) * 10
        params["oq"] = query
        if kwargs.get("rn"):
            params["rn"] = kwargs["rn"]
        return params


_search_engines = {
    "Google": GoogleSearch,
    "DuckDuckGo": DuckDuckGoSearch,
    "Baidu": BaiduSearch,
    "Google Scholar": GoogleScholarSearch,
    "GitHub": GithubSearch,
    "YouTube": YoutubeSearch,
}

supported_search_engines = list(_search_engines.keys())


async def fetch_search_results(
    engine, keyword, page=1, num_results=10
) -> Tuple[Union[List[SearchItem], None], str]:
    error_msg = ""
    search_engine = _search_engines[engine]()
    if engine == "Google":
        num_param = {"num": num_results}
    # elif engine == "Baidu":
    #     num_param = {"rn": num_results}
    else:
        num_param = {}
    search_url = search_engine.get_search_url(keyword, page=page, **num_param)
    log.info(f"search url: {search_url}")
    try:
        results = await search_engine.async_search(
            keyword, page=page, **num_param, cache=False
        )
    except NoResultsOrTrafficError as e:
        results = None
        error_msg = str(e)
        log.error(f"Search error: {e}")
    return results, error_msg


@st.cache_data
def search(
    search_engine, query_keyword, page_num, num_results
) -> Tuple[Union[List[SearchItem], None], str]:
    return asyncio.run(
        fetch_search_results(
            search_engine,
            query_keyword,
            page=page_num,
            num_results=num_results,
        )
    )


def search_preview(search_engine, query_keyword, page_num, num_results):
    if query_keyword:
        results, err = search(
            search_engine,
            query_keyword,
            page_num=page_num,
            num_results=num_results,
        )
        if results:
            st.session_state.search_results[(query_keyword, search_engine)] = results
        else:
            st.toast(":orange-background[没有查询到结果或者查询失败!]", icon="⚠️")
            if err:
                st.toast(err, icon="⚠️")
    else:
        st.toast(":orange-background[请输入关键词进行搜索!]")


def main():
    if "search_results" not in st.session_state:
        st.session_state.search_results = dict()

    st.set_page_config(page_title="Navi Search", layout="wide")
    st.header("欢迎使用 :blue[_Navi Search_] 下载搜索结果", divider="rainbow")
    st.write(
        "支持从 _Google_、_DuckDuckGo_、_Baidu_、_Google Scholar_、_GitHub_、_YouTube_ 搜索。"
    )
    preview_cntr = st.container()
    with st.sidebar:
        st.image("https://img.icons8.com/clouds/500/search.png", width=100)
        st.subheader(":blue[_Navi Search_]", divider="gray")
        selected_engine = st.selectbox(
            "选择搜索引擎", supported_search_engines, key="engine_selector"
        )
        query_keyword = st.text_input(
            "请输入搜索关键词", value="streamlit", key="keyword_input"
        )
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
        if st.session_state.search_results.get((query_keyword, selected_engine)):
            results_df = pd.DataFrame(
                [
                    dict(item)
                    for item in st.session_state.search_results[
                        (query_keyword, selected_engine)
                    ]
                ]
            )
            rows = len(results_df)
            height = int(rows / 5) * 200
            preview_cntr.markdown("**搜索结果预览**")
            preview_cntr.dataframe(
                results_df,
                column_config={
                    "links": st.column_config.LinkColumn("links"),
                },
                hide_index=False,
                height=height,
            )
        else:
            preview_cntr.info("请搜索关键词...")


if __name__ == "__main__":
    main()
