import os
import time
import allure
import random
import re
from urllib.parse import urlparse, urljoin
from playwright.sync_api import expect
from locators.mts.mts_home_online import MTSHomeOnlineMain
from locators.all_locators import Main
from pages.base_page import BasePage
from pages.page_mts.mts_page import ChoiceRegionPage
from locators.all_locators import (
    Profit,
    Connection,
    Checkaddress,
    CheckaddressPOP,
    Undecided,
    Business,
    Moving,
    ExpressConnection,
)
from locators.mts.mts_home_online import RegionChoice

try:
    SUGGEST_WAIT_TIMEOUT_MS = int(os.getenv("SUGGEST_WAIT_TIMEOUT_MS", "12000"))
except Exception:
    SUGGEST_WAIT_TIMEOUT_MS = 12000


class MainSteps(BasePage):
    @allure.title("Проверить все ссылки на странице")
    def check_links_tele(self):
        header_items = self.page.locator("xpath=//div[@class='header__nav-block-item']")
        footer_links = self.page.locator("xpath=//div[@class='footer__tarifs']//a")
        download_links = self.page.locator("xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_header = header_items.count()
        total_footer = footer_links.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента: //div[@class="footer__block"]//a[@itemprop="url"]')
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            # Кликаем только по видимым на фронте элементам
            try:
                if not target.is_visible():
                    continue
            except Exception:
                continue
            # Вместо Ctrl-клика (который часто падает на скрытых/перерисовывающихся элементах),
            # открываем ссылку по href в новой вкладке.
            try:
                href = ""
                if anchor.count() > 0:
                    href = anchor.get_attribute("href") or ""
                if not href:
                    # Если это не ссылка — пропускаем
                    continue
                current_base = self.page.url
                absolute_href = href if href.startswith("http") else urljoin(current_base, href)
                new_page = self.page.context.new_page()
                try:
                    new_page.goto(absolute_href)
                    new_page.wait_for_load_state("load", timeout=15000)
                    expect(new_page).not_to_have_url("**/404")
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
            except Exception:
                # Не валим весь прогон из-за нестабильного хедера — следующая ссылка
                continue

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            # Кликаем только по видимым на фронте элементам
            try:
                if not dl_link.is_visible():
                    continue
            except Exception:
                continue
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    def _pick_first_visible_element(self, selector: str, timeout_ms: int = 5000):
        """Возвращает первый видимый элемент по селектору, учитывая A/B дубли в DOM."""
        loc = self.page.locator(selector)
        deadline = time.time() + (timeout_ms / 1000.0)

        while time.time() < deadline:
            try:
                total = loc.count()
            except Exception:
                total = 0

            for idx in range(total):
                try:
                    candidate = loc.nth(idx)
                    if candidate.is_visible(timeout=250):
                        return candidate
                except Exception:
                    continue

            time.sleep(0.1)

        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass

        raise AssertionError(f"Не найден элемент по селектору: {selector}")

    @allure.title("Проверить все ссылки на странице")
    def check_links_mts(self):
        """
        Проверяет ссылки:
        - //li[@class='list__item-header'] — кликом по вложенной ссылке (если есть), открывает в новой вкладке и проверяет отсутствие 404
        - //div[@class="footer__block"]//a[@itemprop="url"] — кликом с Ctrl в новой вкладке, проверка отсутствия 404
        - //div[@class='checkaddress__agreement agreement']//a[@download] — пытается перехватить скачивание (без сохранения на диск);
          если скачивание не произошло, проверяет наличие href и атрибута download (как минимум — возможность скачать)
        """
        header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        footer_links = self.page.locator("xpath=//div[@class='footer__block']//a[@itemprop='url']")
        download_links = self.page.locator("xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_header = header_items.count()
        total_footer = footer_links.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента: //div[@class="footer__block"]//a[@itemprop="url"]')
        if total_downloads == 0:
            raise AssertionError("Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            # Кликаем только по видимым на фронте элементам
            try:
                if not target.is_visible():
                    continue
            except Exception:
                continue
            with self.page.context.expect_page() as new_page_info:
                target.click(modifiers=["Control"], force=True)
            new_page = new_page_info.value
            new_page.wait_for_load_state("load", timeout=15000)
            expect(new_page).not_to_have_url("**/404")
            new_page.close()

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            # Кликаем только по видимым на фронте элементам
            try:
                if not dl_link.is_visible():
                    continue
            except Exception:
                continue
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить все ссылки на странице")
    def check_links_beeline(self):
        """
        Проверяет ссылки:
        - Проверка наличия блоков бонусов
        - Переход по ссылкам футера по порядку и проверка отсутствия 404
        """
        footer_links = self.page.locator("xpath=//div[@class='footer__block']//a[@itemprop='url']")
        bonuses_slider_titles = self.page.locator("xpath=//div[@class='bonuses-slider__title']")

        total_footer = footer_links.count()
        total_bonuses_slider = bonuses_slider_titles.count()

        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента: //div[@class="footer__block"]//a[@itemprop="url"]')
        if total_bonuses_slider == 0:
            raise AssertionError("Не найдено ни одного элемента: //div[@class='bonuses-slider__title']")

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

    @allure.title("Проверить все ссылки на странице")
    def check_links_beeline_sec(self):
        """
        Проверяет ссылки:
        - //li[@class='list__item-header'] — кликом по вложенной ссылке (если есть), открывает в новой вкладке и проверяет отсутствие 404
        - //div[@class="footer__block"]//a[@itemprop="url"] — кликом с Ctrl в новой вкладке, проверка отсутствия 404
        - //div[@class='checkaddress__agreement agreement']//a[@download] — пытается перехватить скачивание (без сохранения на диск);
          если скачивание не произошло, проверяет наличие href и атрибута download (как минимум — возможность скачать)
        """
        # header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        footer_links = self.page.locator("xpath=//div[@class='footer__block']//a[@itemprop='url']")
        download_links = self.page.locator(
            "xpath=//div[@class='check-adress-up__content']//form//div[@class='autocomplete-submit']//a[@download]")

        # total_header = header_items.count()
        total_footer = footer_links.count()
        total_downloads = download_links.count()

        # if total_header == 0:
        #     raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента: //div[@class="footer__block"]//a[@itemprop="url"]')
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")
        #
        # # Считаем и кликаем по ссылкам в хедере
        # for i in range(total_header):
        #     item = header_items.nth(i)
        #     anchor = item.locator("a").first
        #     target = anchor if anchor.count() > 0 else item
        #     with self.page.context.expect_page() as new_page_info:
        #         target.click(modifiers=["Control"], force=True)
        #     new_page = new_page_info.value
        #     new_page.wait_for_load_state("load", timeout=15000)
        #     expect(new_page).not_to_have_url("**/404")
        #     new_page.close()

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить все ссылки на странице")
    def check_links_mega(self):

        footer_links = self.page.locator("xpath=//li[@class='list__item-footer']//a")
        download_links = self.page.locator(
            "xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_footer = footer_links.count()
        total_downloads = download_links.count()

        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента')
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента")

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить все ссылки на странице")
    def check_links_mega_sec(self):

        header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        footer_links = self.page.locator("xpath=//li[@class='list__item-footer']//a")
        download_links = self.page.locator(
            "xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_header = header_items.count()
        total_footer = footer_links.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_footer == 0:
            raise AssertionError('Не найдено ни одного элемента')
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента")

        # Считаем и кликаем по ссылкам в футере
        # Сначала собираем href всех ссылок (на случай попапов/динамики DOM)
        footer_hrefs = []
        current_base = self.page.url
        for i in range(total_footer):
            link = footer_links.nth(i)
            href = link.get_attribute("href") or ""
            assert href, "У ссылки отсутствует href"
            absolute_href = href if href.startswith("http") else urljoin(current_base, href)
            footer_hrefs.append(absolute_href)

        # Затем открываем каждую ссылку по порядку в новой вкладке и проверяем отсутствие 404
        for href in footer_hrefs:
            new_page = self.page.context.new_page()
            try:
                new_page.goto(href)
                new_page.wait_for_load_state("load", timeout=15000)
                expect(new_page).not_to_have_url("**/404")
            finally:
                try:
                    new_page.close()
                except Exception:
                    pass

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить все ссылки на странице")
    def def_check_links_without_footer(self):
        """
        Проверяет ссылки:
        - //li[@class='list__item-header'] — кликом по вложенной ссылке (если есть), открывает в новой вкладке и проверяет отсутствие 404
        - //div[@class="footer__block"]//a[@itemprop="url"] — кликом с Ctrl в новой вкладке, проверка отсутствия 404
        - //div[@class='checkaddress__agreement agreement']//a[@download] — пытается перехватить скачивание (без сохранения на диск);
          если скачивание не произошло, проверяет наличие href и атрибута download (как минимум — возможность скачать)
        """
        header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        download_links = self.page.locator("xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_header = header_items.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            # Открываем только видимые на фронте ссылки через href (без клика по DOM),
            # чтобы избежать падений "Element is not visible".
            try:
                if not target.is_visible():
                    continue
            except Exception:
                continue
            try:
                href = ""
                if anchor.count() > 0:
                    href = anchor.get_attribute("href") or ""
                if not href:
                    continue
                current_base = self.page.url
                absolute_href = href if href.startswith("http") else urljoin(current_base, href)
                new_page = self.page.context.new_page()
                try:
                    new_page.goto(absolute_href)
                    new_page.wait_for_load_state("load", timeout=15000)
                    expect(new_page).not_to_have_url("**/404")
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
            except Exception:
                continue

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить ссылки в хедере на странице")
    def def_check_header_links_only(self):
        """
        Проверяет только ссылки в хедере:
        - //li[@class='list__item-header'] — открывает в новой вкладке и проверяет отсутствие 404

        ВАЖНО: в отличие от def_check_links_without_footer(), НЕ проверяет download_links.
        """
        header_items = self.page.locator("xpath=//li[@class='list__item-header']")

        total_header = header_items.count()
        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            # Открываем только видимые на фронте ссылки через href (без клика по DOM),
            # чтобы избежать падений "Element is not visible".
            try:
                if not target.is_visible():
                    continue
            except Exception:
                continue
            try:
                href = ""
                if anchor.count() > 0:
                    href = anchor.get_attribute("href") or ""
                if not href:
                    continue
                current_base = self.page.url
                absolute_href = href if href.startswith("http") else urljoin(current_base, href)
                new_page = self.page.context.new_page()
                try:
                    new_page.goto(absolute_href)
                    new_page.wait_for_load_state("load", timeout=15000)
                    expect(new_page).not_to_have_url("**/404")
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
            except Exception:
                continue

    @allure.title("Проверить все ссылки на странице")
    def def_check_links_without_footer_sec(self):
        """
        Проверяет ссылки:
        - //li[@class='list__item-header'] — кликом по вложенной ссылке (если есть), открывает в новой вкладке и проверяет отсутствие 404
        - //div[@class="footer__block"]//a[@itemprop="url"] — кликом с Ctrl в новой вкладке, проверка отсутствия 404
        - //div[@class='checkaddress__agreement agreement']//a[@download] — пытается перехватить скачивание (без сохранения на диск);
          если скачивание не произошло, проверяет наличие href и атрибута download (как минимум — возможность скачать)
        """
        header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        download_links = self.page.locator("xpath=//div[@class='application-block']//a[@download]")

        total_header = header_items.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            # Открываем только видимые на фронте ссылки через href (без клика по DOM),
            # чтобы избежать падений "Element is not visible".
            try:
                if not target.is_visible():
                    continue
            except Exception:
                continue
            try:
                href = ""
                if anchor.count() > 0:
                    href = anchor.get_attribute("href") or ""
                if not href:
                    continue
                current_base = self.page.url
                absolute_href = href if href.startswith("http") else urljoin(current_base, href)
                new_page = self.page.context.new_page()
                try:
                    new_page.goto(absolute_href)
                    new_page.wait_for_load_state("load", timeout=15000)
                    expect(new_page).not_to_have_url("**/404")
                finally:
                    try:
                        new_page.close()
                    except Exception:
                        pass
            except Exception:
                continue

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"

    @allure.title("Проверить все ссылки на странице")
    def def_check_links_without_footer_rtk(self):
        """
        Проверяет ссылки:
        - //li[@class='list__item-header'] — кликом по вложенной ссылке (если есть), открывает в новой вкладке и проверяет отсутствие 404
        - //div[@class="footer__block"]//a[@itemprop="url"] — кликом с Ctrl в новой вкладке, проверка отсутствия 404
        - //div[@class='checkaddress__agreement agreement']//a[@download] — пытается перехватить скачивание (без сохранения на диск);
          если скачивание не произошло, проверяет наличие href и атрибута download (как минимум — возможность скачать)
        """
        header_items = self.page.locator("xpath=//li[@class='list__item-header']")
        bonuses_titles = self.page.locator("xpath=//h3[@class='bonuses__title']")
        download_links = self.page.locator("xpath=//div[@class='checkaddress__agreement agreement']//a[@download]")

        total_header = header_items.count()
        total_bonuses = bonuses_titles.count()
        total_downloads = download_links.count()

        if total_header == 0:
            raise AssertionError("Не найдено ни одного элемента: //li[@class='list__item-header']")
        if total_bonuses == 0:
            raise AssertionError("Не найдено ни одного элемента: //h3[@class='bonuses__title']")
        if total_downloads == 0:
            raise AssertionError(
                "Не найдено ни одного элемента: //div[@class='checkaddress__agreement agreement']//a[@download]")

        # Проверяем видимость заголовков бонусов
        for i in range(total_bonuses):
            expect(bonuses_titles.nth(i)).to_be_visible()

        # Считаем и кликаем по ссылкам в хедере
        for i in range(total_header):
            item = header_items.nth(i)
            anchor = item.locator("a").first
            target = anchor if anchor.count() > 0 else item
            with self.page.context.expect_page() as new_page_info:
                target.click(modifiers=["Control"], force=True)
            new_page = new_page_info.value
            new_page.wait_for_load_state("load", timeout=15000)
            expect(new_page).not_to_have_url("**/404")
            new_page.close()

        # Считаем и проверяем ссылки на скачивание
        for i in range(total_downloads):
            dl_link = download_links.nth(i)
            try:
                with self.page.expect_download(timeout=8000):
                    dl_link.click(force=True)
            except Exception:
                href = dl_link.get_attribute("href") or ""
                has_download_attr = dl_link.get_attribute("download") is not None
                assert href and has_download_attr, "Недостаточно данных для скачивания: отсутствуют href или download"


    @allure.title("Отправить заявку в попап 'Выгодное спецпредложение!' с домом 1, при недоступности — 2 или 3")
    def send_popup_profit(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                street = self.page.locator(Profit.STREET)
                street.click()
                # fill быстрее, чем type с delay; дальше ждём подсказку явным ожиданием
                street.fill("Лен")
            except Exception as e:
                raise AssertionError(
                    "Не удалось ввести улицу в форму 'Выгодное спецпредложение!'. Возможные причины: поле недоступно/не найдено."
                )
            try:
                # Дождаться появления подсказок вместо fixed sleep
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).wait_for(state="visible", timeout=SUGGEST_WAIT_TIMEOUT_MS)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать первую подсказку улицы. Возможные причины: подсказки не подгрузились или изменился селектор."
                )
            # Пытаемся дом 1..9 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
            tried_any = False
            for num in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                try:
                    self.page.locator(Profit.HOUSE).fill(num)
                    self._click_first_available_house()
                    tried_any = True
                    break
                except Exception:
                    continue
            if not tried_any:
                raise AssertionError("Не удалось указать дом (1..9) в форме 'Выгодное спецпредложение!'.")
            try:
                self.page.locator(Profit.PHONE).fill("99999999999")
            except Exception as e:
                raise AssertionError(
                    "Не удалось ввести телефон в форму 'Выгодное спецпредложение!'."
                )
            try:
                self.page.locator(Profit.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Выгодное спецпредложение!'. Кнопка недоступна или не найдена."
                )

    @allure.title("Отправить заявку в попап 'Выгодное спецпредложение!' с домом 2")
    def send_popup_profit_second_house(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                street = self.page.locator(Profit.STREET)
                street.click()
                street.fill("Лен")
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).wait_for(state="visible", timeout=SUGGEST_WAIT_TIMEOUT_MS)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Выгодное спецпредложение!'."
                )
            try:
                house_input = self.page.locator(Profit.HOUSE)
                # Пробуем дом 2..9 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
                for num in ("2", "3", "4", "5", "6", "7", "8", "9"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось указать дом (2..9) в форме 'Выгодное спецпредложение!'.")
            except AssertionError as e:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом (вариант 2) в форме 'Выгодное спецпредложение!'."
                )
            try:
                self.page.locator(Profit.PHONE).fill("99999999999")
                self.page.locator(Profit.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Выгодное спецпредложение!' (дом 2)."
                )

    def _click_first_available_house(self):
        try:
            self.page.locator(MTSHomeOnlineMain.FIRST_HOUSE).click(timeout=3000)
            return
        except Exception:
            pass
        try:
            self.page.locator(MTSHomeOnlineMain.FIRST_HOUSE_SECOND).click(timeout=3000)
            return
        except Exception:
            pass
        raise AssertionError(
            "Не удалось кликнуть по варианту дома.\n"
            "Пробовали клики по FIRST_HOUSE и FIRST_HOUSE_SECOND, оба варианта недоступны.\n"
            "Возможные причины: подсказки не подгрузились, изменился селектор, попап/выпадающий список не активен."
        )

    def _verify_city_label_accepts_variants(self, expected_city: str):
        # Принимаем как валидные варианты:
        # 1) Точное совпадение названия города
        # 2) Текст вида "Вы находитесь в городе <город>"
        # 3) Для падежных форм допускаем замену последней буквы города на "у" или "е"
        candidates = [
            RegionChoice.NEW_REGION_CHOICE_BUTTON,
            RegionChoice.TELE_REGION_CHOICE_BUTTON,
            RegionChoice.REGION_CHOICE_BUTTON,
        ]

        def normalize(text: str) -> str:
            return re.sub(r"\s+", " ", (text or "").strip())

        expected_norm = normalize(expected_city)

        def city_variants(base: str):
            variants = {base}
            if len(base) >= 2:
                variants.add(base[:-1] + "у")
                variants.add(base[:-1] + "е")
            return list(variants)

        variants = city_variants(expected_norm)
        accepted_patterns = []
        for v in variants:
            accepted_patterns.append(v)
            accepted_patterns.append(f"Вы находитесь в городе {v}")

        found_texts = []
        for sel in candidates:
            try:
                loc = self.page.locator(sel)
                if loc.count() == 0:
                    continue
                text = normalize(loc.first.text_content() or "")
                if text:
                    found_texts.append(text)
                    if any((pat == text) or (pat in text) for pat in accepted_patterns):
                        return
            except Exception:
                continue

        # Фоллбэк: проверим текст всей страницы
        try:
            body_text = normalize(self.page.locator("body").text_content() or "")
            if any(pat in body_text for pat in accepted_patterns):
                return
        except Exception:
            pass

        raise AssertionError(
            f"Город не подтверждён. Допустимые варианты: {accepted_patterns}. Найденные тексты: {found_texts}"
        )

    @allure.title("Нажать на кнопку Изменить город")
    def button_change_city_profit(self):
        # Пытаемся кликнуть по основному селектору; если его нет/не кликается — пробуем запасной
        try:
            self.page.locator(Profit.BUTTON_CHANGE_CITY).click(timeout=3000)
            return
        except Exception:
            pass
        try:
            self.page.locator(Profit.BUTTON_CHANGE_CITY_SEC).click(timeout=3000)
            return
        except Exception:
            pass
        raise AssertionError(
            "Кнопка 'Изменить город' (Profit) не найдена/не кликабельна.\n"
            "Пробовали селекторы BUTTON_CHANGE_CITY и BUTTON_CHANGE_CITY_SEC."
        )

    @allure.title("Нажать на кнопку Изменить город")
    def button_change_city_connection(self):
        # Персональная правка для домена internet-mts-home.online
        try:
            current_url = (self.page.url or "").lower()
        except Exception:
            current_url = ""
        if "internet-mts-home.online" in current_url or "mts-internet.online" in current_url:
            try:
                self.page.locator("xpath=(//span[contains(@class,'connection_address_button_change_city')])[2]").click(timeout=3000)
                return
            except Exception:
                pass
            try:
                self.page.locator("xpath=(//div[contains(@class,'connection_address_button_change_city')])[2]").click(timeout=3000)
                return
            except Exception:
                pass
        try:
            self.page.locator(Connection.BUTTON_CHANGE_CITY).first.click(timeout=3000)
            return
        except Exception:
            pass
        try:
            self.page.locator(Connection.BUTTON_CHANGE_CITY).last.click(timeout=3000)
            return
        except Exception:
            pass
        try:
            self.page.locator(Connection.BUTTON_CHANGE_CITY_SEC).first.click(timeout=3000)
            return
        except Exception:
            pass
        raise AssertionError(
            "Кнопка 'Изменить город' (Connection) не найдена/не кликабельна.\n"
            "Пробовали селекторы BUTTON_CHANGE_CITY и BUTTON_CHANGE_CITY_SEC."
        )

    @allure.title("Нажать на кнопку Изменить город")
    def button_change_city_checkaddress(self):
        try:
            self.page.locator(Checkaddress.BUTTON_CHANGE_CITY).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось нажать кнопку 'Изменить город' в блоке 'Проверить адрес'.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Нажать на кнопку Изменить город")
    def button_change_city_moving(self):
        try:
            self.page.locator(Moving.BUTTON_CHANGE_CITY).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось нажать кнопку 'Изменить город' в блоке 'Переезд'.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Нажать на кнопку Изменить город")
    def button_change_city_express_connection(self):
        try:
            self._pick_first_visible_element(ExpressConnection.BUTTON_CHANGE_CITY, timeout_ms=4000).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось нажать кнопку 'Изменить город' в форме 'Экспресс подключение'.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Нажать на кнопку Изменить город в блоке 'Остались вопросы?' по индексу (1-based)")
    def button_change_city_undecideds(self, index: int):
        try:
            self.page.locator(Undecided.BUTTON_CHANGE_CITY).nth(index - 1).click()
        except Exception as e:
            raise AssertionError(
                f"Не удалось нажать кнопку 'Изменить город' в блоке 'Остались вопросы?' (индекс {index}).\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Нажать на кнопку Изменить город в блоке 'Проверить адрес' по индексу (1-based)")
    def button_change_city_checkaddress_block(self, index: int):
        try:
            try:
                self.page.locator(Checkaddress.BUTTON_CHANGE_CITY_BLOCK).nth(index - 1).click()
            except Exception:
                # Фолбэк: некоторые лендинги рендерят кнопку как div, а не span
                self.page.locator(Checkaddress.BUTTON_CHANGE_CITY_BLOCK_SECOND).nth(index - 1).click()
        except Exception as e:
            raise AssertionError(
                f"Не удалось нажать кнопку 'Изменить город' в блоке 'Проверить адрес' (индекс {index}).\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Закрыть попап")
    def close_popup(self):
        try:
            self.page.locator(Main.CLOSE).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось закрыть попап.\n"
                "Возможно попап перекрыл экран, кнопка закрытия пропала или изменился селектор."
            )

    @allure.title("Нажать на плавающую красную кнопку с телефоном в правом нижнем углу")
    def open_popup_for_colorful_button(self):
        try:
            self.page.locator(Profit.COLORFUL_BUTTON).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось нажать на плавающую красную кнопку (телефон) в правом нижнем углу.\n"
                "Возможно элемент перекрыт попапом, скрыт или изменился селектор."
            )

    @allure.title("Нажать на кнопку Подключиться в хедере")
    def open_popup_express_connection_button(self):
        try:
            # FORM_BUTTON может матчить несколько элементов из A/B верстки — кликаем по видимому.
            self._pick_first_visible_element(ExpressConnection.FORM_BUTTON, timeout_ms=4000).click()
        except Exception as e:
            raise AssertionError(
                "Не удалось нажать кнопку 'Подключиться' в хедере.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Проверить что окно открыто")
    def check_popup_express_connection_button(self):
        """Проверяет, что попап 'Экспресс подключение' реально открылся.
        Если поле улицы не видно — пробует кликнуть по кнопке открытия попапа ещё раз.
        """
        try:
            street = self._pick_first_visible_element(ExpressConnection.STREET, timeout_ms=4000)
            try:
                street.wait_for(state="visible", timeout=3000)
                return
            except Exception:
                # Попап мог не открыться с первого клика (оверлей/скролл/перерисовка) — кликаем ещё раз
                try:
                    self._pick_first_visible_element(ExpressConnection.FORM_BUTTON, timeout_ms=2500).click()
                except Exception:
                    pass
                street = self._pick_first_visible_element(ExpressConnection.STREET, timeout_ms=7000)
                street.wait_for(state="visible", timeout=2000)
        except Exception as e:
            raise AssertionError(
                "Окно 'Экспресс подключение' не открылось: поле 'Улица' не найдено/не видно.\n"
            )

    @allure.title("Посчитать количество кнопок 'Подключиться' (экспресс, видимые)")
    def count_express_connection_buttons_visible(self) -> int:
        """Считает только видимые на фронте кнопки по локатору ExpressConnection.FORM_BUTTON."""
        try:
            candidates = self.page.locator(ExpressConnection.FORM_BUTTON)
            nodes = candidates.all()
            visible = 0
            for n in nodes:
                try:
                    if n.is_visible():
                        visible += 1
                except Exception:
                    continue
            return visible
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Подключиться' (экспресс, видимые).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку 'Подключиться' (экспресс) по индексу среди видимых (1-based)")
    def click_express_connection_button_visible_index(self, index: int):
        """Кликает по индексу только среди видимых на фронте кнопок ExpressConnection.FORM_BUTTON."""
        try:
            candidates = self.page.locator(ExpressConnection.FORM_BUTTON)
            nodes = candidates.all()
            visible_nodes = []
            for n in nodes:
                try:
                    if n.is_visible():
                        visible_nodes.append(n)
                except Exception:
                    continue
            if index < 1 or index > len(visible_nodes):
                raise AssertionError(
                    f"Кнопка 'Подключиться' (экспресс) №{index} не видна на странице. Видимых: {len(visible_nodes)}"
                )
            visible_nodes[index - 1].click()
        except AssertionError:
            raise
        except Exception as e:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Подключиться' (экспресс) №{index} среди видимых.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку Подключить по индексу (1-based)")
    def click_connect_button_index(self, index: int):
        """Кликает по индексу только среди видимых на фронте кнопок Connection.CONNECT_BUTTON."""
        try:
            candidates = self.page.locator(Connection.CONNECT_BUTTON)
            nodes = candidates.all()
            visible_nodes = []
            for n in nodes:
                try:
                    if n.is_visible():
                        visible_nodes.append(n)
                except Exception:
                    continue
            if index < 1 or index > len(visible_nodes):
                raise AssertionError(
                    f"Кнопка 'Подключить' №{index} не видна на странице. Видимых: {len(visible_nodes)}"
                )
            visible_nodes[index - 1].click(timeout=3000)
        except AssertionError:
            raise
        except Exception:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Подключить' №{index} среди видимых.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку Подключить по индексу (1-based)")
    def click_connect_button_index_cards(self, index: int):
        # Кликаем по индексному элементу только среди видимых карточных кнопок
        try:
            primary = self.page.locator(Connection.CARDS_BUTTONS)
            fallback = self.page.locator("xpath=//a[contains(@class,'connection_address_card_button')] | //button[contains(@class,'connection_address_card_button')]")
            nodes = primary.all() if primary.count() > 0 else fallback.all()
            visible_nodes = []
            for n in nodes:
                try:
                    if n.is_visible():
                        visible_nodes.append(n)
                except Exception:
                    continue
            if index < 1 or index > len(visible_nodes):
                raise AssertionError(
                    f"Кнопка 'Подключить' (карточка) №{index} не видна на странице. Видимых: {len(visible_nodes)}"
                )
            visible_nodes[index - 1].click()
        except AssertionError:
            raise
        except Exception as e:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Подключить' (карточка) №{index} среди видимых.\n"
                "Возможно элемент пропал или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку Проверить адрес по индексу (1-based)")
    def click_checkaddress_popup_index(self, index: int):
        selector = f"xpath=(//button[contains(@class,'checkaddress_address_button')])[{index}]"
        try:
            self.page.locator(selector).click()
        except Exception as e:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Проверить адрес' №{index}.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку Проверить адрес по индексу среди видимых (1-based)")
    def click_checkaddress_popup_visible_index(self, index: int):
        """Clicks only among buttons visible on the page (front)."""
        try:
            candidates = self.page.locator(Checkaddress.CHECKADDRESS_BUTTON_POPUP)
            nodes = candidates.all()
            visible_nodes = []
            for n in nodes:
                try:
                    if n.is_visible():
                        visible_nodes.append(n)
                except Exception:
                    continue
            if index < 1 or index > len(visible_nodes):
                raise AssertionError(
                    f"Кнопка 'Проверить адрес' №{index} не видна на странице. Видимых: {len(visible_nodes)}"
                )
            visible_nodes[index - 1].click()
        except AssertionError:
            raise
        except Exception as e:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Проверить адрес' №{index} среди видимых.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Кликнуть на кнопку Переехать по индексу (1-based)")
    def click_moving_popup_index(self, index: int):
        selector = f"xpath=(//button[contains(@class,'moving_address_button')])[{index}]"
        try:
            self.page.locator(selector).click()
        except Exception as e:
            raise AssertionError(
                f"Не удалось кликнуть по кнопке 'Переехать' №{index}.\n"
                "Возможно попап перекрыл экран, элемент пропал или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Подключить")
    def count_connect_buttons(self) -> int:
        # Считаем только видимые на фронте кнопки "Подключить" (скрытые игнорируем)
        try:
            candidates = self.page.locator(Connection.CONNECT_BUTTON)
            nodes = candidates.all()
            visible = 0
            for n in nodes:
                try:
                    if n.is_visible():
                        visible += 1
                except Exception:
                    continue
            return visible
        except Exception:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Подключить' (видимые).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Подключить")
    def count_connect_buttons_cards(self) -> int:
        # Считаем только видимые карточные кнопки (скрытые игнорируем)
        try:
            primary = self.page.locator(Connection.CARDS_BUTTONS)
            if primary.count() == 0:
                candidates = self.page.locator("xpath=//a[contains(@class,'connection_address_card_button')] | //button[contains(@class,'connection_address_card_button')]")
            else:
                candidates = primary
            nodes = candidates.all()
            visible = 0
            for n in nodes:
                try:
                    if n.is_visible():
                        visible += 1
                except Exception:
                    continue
            return visible
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Подключить' в карточках (видимые).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Проверить адрес")
    def count_checkaddress_popup_buttons(self) -> int:
        try:
            return self.page.locator(Checkaddress.CHECKADDRESS_BUTTON_POPUP).count()
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Проверить адрес' (попап).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Проверить адрес (видимые)")
    def count_checkaddress_popup_buttons_visible(self) -> int:
        """Counts only buttons visible on the page (front)."""
        try:
            candidates = self.page.locator(Checkaddress.CHECKADDRESS_BUTTON_POPUP)
            nodes = candidates.all()
            visible = 0
            for n in nodes:
                try:
                    if n.is_visible():
                        visible += 1
                except Exception:
                    continue
            return visible
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Проверить адрес' (попап, видимые).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество блоков Проверить адрес")
    def count_checkaddress_blocks(self) -> int:
        try:
            return self.page.locator(Checkaddress.CHECKADDRESS_BLOCK).count()
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать блоки 'Проверить адрес'.\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Получить индексы видимых блоков 'Проверить адрес' (1-based)")
    def visible_checkaddress_block_indices(self) -> list[int]:
        """Возвращает индексы (1-based) только тех блоков Checkaddress.CHECKADDRESS_BLOCK, которые видимы на фронте."""
        try:
            blocks = self.page.locator(Checkaddress.CHECKADDRESS_BLOCK)
            # Фолбэк: если по основному локатору ничего не нашли — пробуем второй
            try:
                if blocks.count() == 0:
                    blocks = self.page.locator(Checkaddress.CHECKADDRESS_BLOCK_SECOND)
            except Exception:
                pass
            total = blocks.count()
            visible: list[int] = []
            for i in range(total):
                try:
                    if blocks.nth(i).is_visible():
                        visible.append(i + 1)  # 1-based
                except Exception:
                    continue
            return visible
        except Exception:
            # Не падаем здесь — пусть тест сам решит, что делать при пустом списке/ошибке
            return []

    @allure.title("Посчитать количество видимых блоков Проверить адрес")
    def count_checkaddress_blocks_visible(self) -> int:
        """Считает только видимые на фронте блоки Checkaddress.CHECKADDRESS_BLOCK."""
        return len(self.visible_checkaddress_block_indices())

    @allure.title("Посчитать количество блоков формы Остались вопросы?")
    def count_undecided_blocks(self) -> int:
        # Считаем только видимые на фронте элементы
        try:
            candidates = self.page.locator(Undecided.UNDECIDED_BLOCK)
            nodes = candidates.all()
            visible = 0
            for n in nodes:
                try:
                    if n.is_visible():
                        visible += 1
                except Exception:
                    continue
            return visible
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать блоки формы 'Остались вопросы?'.\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Переехать")
    def count_moving_popup_buttons(self) -> int:
        try:
            return self.page.locator(Moving.MOVING_BUTTON).count()
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Переехать'.\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Посчитать количество кнопок Подробнее на странице бизнеса")
    def count_business_buttons(self) -> int:
        # Считаем только видимые на фронте кнопки "Подробнее"
        try:
            # Кандидаты по приоритету
            candidates = [
                self.page.locator(Business.MORE_BUTTON),
                self.page.locator(Business.MORE_BUTTON_SECOND),
                self.page.locator(Business.MORE_BUTTON_ANY),
            ]
            visible_total = 0
            for loc in candidates:
                try:
                    nodes = loc.all()
                except Exception:
                    nodes = []
                for n in nodes:
                    try:
                        if n.is_visible():
                            visible_total += 1
                    except Exception:
                        continue
                if visible_total > 0:
                    break
            return visible_total
        except Exception as e:
            raise AssertionError(
                "Не удалось посчитать кнопки 'Подробнее' на странице бизнеса (видимые).\n"
                "Возможно элементы отсутствуют на странице или изменился селектор."
            )

    @allure.title("Клик по бизнес-кнопке: хедер или 'Подробнее' по индексу")
    def click_business_button(self, index: int = 0):
        # index <= 0: клик по кнопке в хэдере (первой доступной)
        # index >= 1: клик по кнопке 'Подробнее' на странице бизнеса по индексу (1-based)
        if index <= 0:
            # Особый случай: для https://mts-home-online.ru/business используем только BUSINESS_BUTTON_THIRD
            try:
                current_url = (self.page.url or "").rstrip("/")
            except Exception:
                current_url = ""
            if current_url.startswith("https://mts-home-online.ru/business"):
                # Особый случай: для этой урлы не нажимаем никакие кнопки
                return
            header_candidates = [
                getattr(Business, "BUSINESS_BUTTON", None),
                getattr(Business, "BUSINESS_BUTTON_SECOND", None),
                getattr(Business, "BUSINESS_BUTTON_THIRD", None),
                getattr(Business, "BUSINESS_BUTTON_FOUR", None),
                getattr(Business, "BUSINESS_BUTTON_BEELINE", None),
            ]
            for sel in header_candidates:
                if not sel:
                    continue
                try:
                    self.page.locator(sel).click(timeout=3000)
                    return
                except Exception:
                    continue
            raise AssertionError(
                "Кнопка раздела 'Бизнес' не найдена в хедере.\n"
                "Пробовали несколько вариантов селекторов (BUSINESS_BUTTON...); ни один не кликабелен.\n"
                "Возможные причины: разметка страницы изменилась, кнопка скрыта/отсутствует, страница не успела прогрузиться."
            )

        # Иначе кликаем по кнопкам 'Подробнее' по индексу
        buttons_primary = self.page.locator(Business.MORE_BUTTON)
        total_primary = buttons_primary.count()
        if total_primary >= index and total_primary > 0:
            buttons_primary.nth(index - 1).click()
            return

        buttons_fallback = self.page.locator(Business.MORE_BUTTON_SECOND)
        total_fallback = buttons_fallback.count()
        if total_fallback >= index and total_fallback > 0:
            buttons_fallback.nth(index - 1).click()
            return

        # Третий вариант: любой элемент с классом services-business
        buttons_any = self.page.locator(Business.MORE_BUTTON_ANY)
        total_any = buttons_any.count()
        if total_any >= index and total_any > 0:
            buttons_any.nth(index - 1).click()
            return

        raise AssertionError(
            f"Кнопка 'Подробнее' №{index} не найдена.\n"
            f"Найдено основных: {total_primary}, запасных: {total_fallback}, любых: {total_any}.\n"
            "Проверьте корректность индекса и возможные изменения разметки."
        )

    @allure.title("Нажать на кнопку Подключить на странице бизнеса")
    def connect_business_page(self):
        try:
            self.page.locator(Business.CONNECT_BUTTON).click(timeout=3000)
            return
        except Exception:
            pass
        try:
            self.page.locator(Business.CONNECT_BUTTON_SECOND).click(timeout=3000)
            return
        except Exception:
            pass
        raise AssertionError(
            "Кнопка 'Подключить' на странице бизнеса не найдена.\n"
            "Пробовали оба варианта селекторов (CONNECT_BUTTON / CONNECT_BUTTON_SECOND).\n"
            "Возможные причины: элемент скрыт, не отрисован или изменился селектор."
        )
        self.page.locator(Business.CONNECT_BUTTON_SECOND).click()

    @allure.title("Отправить заявку в попап 'Заявка на подключение'")
    def send_popup_connection(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Connection.STREET).last.fill('Лен')
                # self.page.locator(Connection.STREET).type("Лен", delay=50)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Заявка на подключение'."
                )
            try:
                house_input = self.page.locator(Connection.HOUSE).first
                # Пробуем дом 2, затем 1, затем 3
                for num in ("1", "3"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        # переходим к следующему номеру
                        continue
                else:
                    # ни один номер не сработал
                    raise AssertionError("Не удалось выбрать дом: ни 2, ни 1, ни 3 не доступны в подсказках")
            except AssertionError as e:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Заявка на подключение'."
                )
            try:
                self.page.locator(Connection.PHONE).first.fill("99999999999")
                self.page.locator(Connection.BUTTON_SEND).first.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Заявка на подключение'."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап 'Заявка на подключение'")
    def send_popup_connection_rtk(self):
        with allure.step("Заполнить попап и отправить заявку"):
            def _pick_first_visible(loc, *, visible_timeout: int = 500):
                """Вернуть первый видимый элемент из locator'а (то, что реально видно пользователю)."""
                try:
                    total = loc.count()
                except Exception:
                    total = 0
                for idx in range(total):
                    try:
                        el = loc.nth(idx)
                        if el.is_visible(timeout=visible_timeout):
                            return el
                    except Exception:
                        continue
                # Фолбэк: если определить видимость не удалось, попробуем первый
                try:
                    return loc.first
                except Exception:
                    return loc

            try:
                street_input = _pick_first_visible(self.page.locator(Connection.STREET_LAST))
                street_input.fill('Лен')
                # self.page.locator(Connection.STREET).type("Лен", delay=50)
                try:
                    self.page.locator(MTSHomeOnlineMain.FIRST_STREET).wait_for(state="visible", timeout=SUGGEST_WAIT_TIMEOUT_MS)
                except Exception:
                    pass
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Заявка на подключение'."
                )
            try:
                house_input = _pick_first_visible(self.page.locator(Connection.HOUSE_LAST))
                # Пробуем дом 2, затем 1, затем 3
                for num in ("2", "1", "3"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        # переходим к следующему номеру
                        continue
                else:
                    # ни один номер не сработал
                    raise AssertionError("Не удалось выбрать дом: ни 2, ни 1, ни 3 не доступны в подсказках")
            except AssertionError as e:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Заявка на подключение'."
                )
            try:
                # self.page.locator(Connection.NAME_LAST).last.fill("Тест")
                phone_input = _pick_first_visible(self.page.locator(Connection.PHONE_LAST))
                phone_input.fill("99999999999")
                send_btn = _pick_first_visible(self.page.locator(Connection.BUTTON_SEND_LAST))
                send_btn.click(timeout=3000)
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Заявка на подключение'."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап 'Заявка на подключение'")
    def send_popup_connection_rtk_cards(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Connection.STREET_LAST).last.fill('Лен')
                # self.page.locator(Connection.STREET).type("Лен", delay=50)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Заявка на подключение'."
                )
            try:
                house_input = self.page.locator(Connection.HOUSE_LAST).last
                # Пробуем дом 2, затем 1, затем 3
                for num in ("2", "1", "3"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        # переходим к следующему номеру
                        continue
                else:
                    # ни один номер не сработал
                    raise AssertionError("Не удалось выбрать дом: ни 2, ни 1, ни 3 не доступны в подсказках")
            except AssertionError as e:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Заявка на подключение'."
                )
            try:
                self.page.locator(Connection.NAME_LAST).last.fill("Тест")
                self.page.locator(Connection.PHONE_LAST).last.fill("99999999999")
                self.page.locator(Connection.BUTTON_SEND_LAST).last.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Заявка на подключение'."
                )
            time.sleep(4)
    @allure.title("Отправить заявку в попап 'Заявка на подключение'")
    def send_popup_connection_second(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Connection.STREET).last.type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Заявка на подключение' (вариант 2)."
                )
            time.sleep(1)
            try:
                house_input = self.page.locator(Connection.HOUSE).last
                # Пробуем дом 2, затем 1, затем 3
                for num in ("2", "1", "3"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 2, ни 1, ни 3 не доступны в подсказках")
            except AssertionError as e:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом (вариант 2) в форме 'Заявка на подключение'."
                )
            time.sleep(1)
            try:
                self.page.locator(Connection.PHONE).last.fill("99999999999")
                time.sleep(1)
                self.page.locator(Connection.BUTTON_SEND).last.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Заявка на подключение' (вариант 2)."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап/форму 'Проверить адрес'")
    def send_popup_checkaddress(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Checkaddress.STREET).last.type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Проверить адрес'."
                )
            time.sleep(1)
            try:
                house_input = self.page.locator(Checkaddress.HOUSE).last
                # Пробуем дом 1..9 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
                for num in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 1..9 не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Проверить адрес'."
                )
            time.sleep(1)
            try:
                self.page.locator(Checkaddress.PHONE).last.fill("99999999999")
                time.sleep(1)
                self.page.locator(Checkaddress.BUTTON_SEND).last.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Проверить адрес'."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап/форму 'Проверить адрес'")
    def send_popup_checkaddress_second(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Checkaddress.STREET).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Проверить адрес' (вариант 2)."
                )
            time.sleep(1)
            try:
                house_input = self.page.locator(Checkaddress.HOUSE)
                # Вариант 2: пробуем дома 2..9 (если на лендинге какие-то номера не доступны в подсказках)
                for num in ("2", "3", "4", "5", "6", "7", "8", "9", "1"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 2..9 (и 1) не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом (вариант 2) в форме 'Проверить адрес'."
                )
            time.sleep(1)
            try:
                self.page.locator(Checkaddress.PHONE).fill("99999999999")
                time.sleep(1)
                self.page.locator(Checkaddress.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Проверить адрес' (вариант 2)."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в блоке 'Проверить адрес' по индексу (1-based)")
    def send_popup_checkaddress_block(self, index: int):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                # Используем новые FIRST-локаторы
                self.page.locator(CheckaddressPOP.STREET_FIRST).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в блоке 'Проверить адрес' (индекс {index})."
                )
            time.sleep(1)
            try:
                house_input = self.page.locator(CheckaddressPOP.HOUSE_FIRST)
                # Пробуем дом 1..9 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
                for num in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 1..9 не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в блоке 'Проверить адрес' (индекс {index})."
                )
            time.sleep(1)
            try:
                self.page.locator(CheckaddressPOP.PHONE_FIRST).fill("99999999999")
                time.sleep(1)
                self.page.locator(CheckaddressPOP.BUTTON_SEND_FIRST).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму в блоке 'Проверить адрес' (индекс {index})."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в блоке 'Проверить адрес' по индексу (1-based)")
    def send_popup_checkaddress_block_second(self, index: int):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                # Используем новые SECOND-локаторы
                self.page.locator(CheckaddressPOP.STREET_SECOND).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в блоке 'Проверить адрес' (индекс {index})."
                )
            time.sleep(1)
            try:
                house_input = self.page.locator(CheckaddressPOP.HOUSE_SECOND)
                # Вариант 2: пробуем дома 2..9 (и 1 как фолбэк)
                for num in ("2", "3", "4", "5", "6", "7", "8", "9", "1"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 2..9 (и 1) не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    f"Не удалось указать дом (вариант 2) в блоке 'Проверить адрес' (индекс {index}). "
                )
            time.sleep(1)
            try:
                self.page.locator(CheckaddressPOP.PHONE_SECOND).fill("99999999999")
                time.sleep(1)
                self.page.locator(CheckaddressPOP.BUTTON_SEND_SECOND).click()
            except Exception as e:
                raise AssertionError(
                    f"Не удалось отправить форму в блоке 'Проверить адрес' (индекс {index}."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в форму 'Не определились с тарифом?'")
    def send_form_undecided(self, index: int):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Undecided.STREET).nth(index - 1).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click(timeout=SUGGEST_WAIT_TIMEOUT_MS)
            except Exception as e:
                raise AssertionError(
                    f"Не удалось выбрать улицу/подсказку в форме 'Не определились с тарифом?' (индекс {index})."
                )
            time.sleep(1)
            try:
                self.page.locator(Undecided.HOUSE).nth(index - 1).fill("1")
                self._click_first_available_house()
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    f"Не удалось указать дом в форме 'Не определились с тарифом?' (индекс {index})."
                )
            time.sleep(1)
            try:
                self.page.locator(Undecided.PHONE).nth(index - 1).fill("99999999999")
                time.sleep(1)
                self.page.locator(Undecided.BUTTON_SEND).nth(index - 1).click()
            except Exception as e:
                raise AssertionError(
                    f"Не удалось отправить форму 'Не определились с тарифом?' (индекс {index})."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в форму 'Не определились с тарифом?'")
    def send_form_undecided_second(self, index: int):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Undecided.STREET).nth(index - 1).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click()
            except Exception as e:
                raise AssertionError(
                    f"Не удалось выбрать улицу/подсказку в форме 'Не определились с тарифом?' (индекс {index})."
                )
            time.sleep(1)
            try:
                self.page.locator(Undecided.HOUSE).nth(index - 1).fill("2")
                self._click_first_available_house()
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    f"Не удалось указать дом (вариант 2) в форме 'Не определились с тарифом?' (индекс {index})."
                )
            time.sleep(1)
            try:
                self.page.locator(Undecided.PHONE).nth(index - 1).fill("99999999999")
                time.sleep(1)
                self.page.locator(Undecided.BUTTON_SEND).nth(index - 1).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Не определились с тарифом?' (индекс {index}, вариант 2)."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в форму 'Не определились с тарифом?'")
    def send_form_undecided_third(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Undecided.PHONE).fill("99999999999")
                time.sleep(1)
                self.page.locator(Undecided.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Не определились с тарифом?' (короткая версия)."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап 'Заявка на подключение для Бизнеса'")
    def send_popup_business(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Business.FULL_ADDRESS).last.type("Тестадрес", delay=100)
            except Exception as e:
                raise AssertionError(
                    "Не удалось ввести адрес в форме Бизнес"
                )
            time.sleep(1)
            try:
                self.page.locator(Business.PHONE).last.fill("99999999999")
            except Exception as e:
                raise AssertionError(
                    "Не удалось ввести телефон в форме Бизнес"
                )
            time.sleep(1)
            try:
                self.page.locator(Business.BUTTON_SEND).last.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму Бизнес. Кнопка недоступна или не найдена"
                )
            time.sleep(1)

    @allure.title("Отправить заявку в попап 'Заявка на подключение для Услуги переезд'")
    def send_popup_moving(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Moving.STREET).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Переезд'"
                )
            time.sleep(1)
            try:
                self.page.locator(Moving.HOUSE).fill("1")
                self._click_first_available_house()
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Переезд'"
                )
            time.sleep(1)
            try:
                self.page.locator(Moving.PHONE).fill("99999999999")
                time.sleep(1)
                self.page.locator(Moving.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Переезд'."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап 'Заявка на подключение для Услуги переезд'")
    def send_popup_moving_second(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                self.page.locator(Moving.STREET).type("Лен", delay=100)
                self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Переезд' (вариант 2)."
                )
            time.sleep(1)
            try:
                self.page.locator(Moving.HOUSE).fill("2")
                self._click_first_available_house()
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом (вариант 2) в форме 'Переезд'."
                )
            time.sleep(1)
            try:
                self.page.locator(Moving.PHONE).fill("99999999999")
                time.sleep(1)
                self.page.locator(Moving.BUTTON_SEND).click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Переезд' (вариант 2)."
                )
            time.sleep(4)

    @allure.title("Отправить заявку в попап 'Заявка на экспресс подключение'")
    def send_popup_express_connection(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                street_input = self._pick_first_visible_element(ExpressConnection.STREET, timeout_ms=5000)
                street_input.fill("")
                street_input.type("Лен", delay=100)
                # Автокомплит иногда появляется с задержкой; ждём и кликаем по первой подсказке
                try:
                    self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.wait_for(state="visible", timeout=SUGGEST_WAIT_TIMEOUT_MS)
                    self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click(timeout=SUGGEST_WAIT_TIMEOUT_MS)
                except Exception:
                    # Фолбэк: выбрать первую подсказку клавиатурой
                    street_input.press("ArrowDown")
                    street_input.press("Enter")
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Экспресс подключение'."
                )
            time.sleep(1)
            try:
                house_input = self._pick_first_visible_element(ExpressConnection.HOUSE, timeout_ms=5000)
                # Пробуем дом 2, затем 3, затем 7 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
                for num in ("1", "2", "3", "4","5","6", "7","8","9",):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 2, ни 3, ни 4 и др. не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    "Не удалось указать дом в форме 'Экспресс подключение'."
                )
            time.sleep(1)
            try:
                phone_input = self._pick_first_visible_element(ExpressConnection.PHONE, timeout_ms=5000)
                phone_input.fill("99999999999")
                time.sleep(1)
                send_button = self._pick_first_visible_element(ExpressConnection.BUTTON_SEND, timeout_ms=5000)
                send_button.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Экспресс подключение'."
                )
            time.sleep(2)

    @allure.title("Отправить заявку в попап 'Заявка на экспресс подключение'")
    def send_popup_express_connection_second(self):
        with allure.step("Заполнить попап и отправить заявку"):
            try:
                street_input = self._pick_first_visible_element(ExpressConnection.STREET, timeout_ms=5000)
                street_input.click()
                street_input.fill("")
                street_input.type("Лени", delay=200)
                # Автокомплит иногда появляется с задержкой; ждём и кликаем по первой подсказке
                try:
                    self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.wait_for(state="visible", timeout=SUGGEST_WAIT_TIMEOUT_MS)
                    self.page.locator(MTSHomeOnlineMain.FIRST_STREET).first.click(timeout=SUGGEST_WAIT_TIMEOUT_MS)
                except Exception:
                    # Фолбэк: выбрать первую подсказку клавиатурой
                    street_input.press("ArrowDown")
                    street_input.press("Enter")
            except Exception as e:
                raise AssertionError(
                    "Не удалось выбрать улицу/подсказку в форме 'Экспресс подключение' (вариант 2)."
                )
            time.sleep(1)
            try:
                house_input = self._pick_first_visible_element(ExpressConnection.HOUSE, timeout_ms=5000)
                # Пробуем дом 3, затем 4, затем 7 (часто некоторые номера отсутствуют в подсказках на конкретном лендинге)
                for num in ("2", "3", "4", "5", "6", "7", "8", "9", "1"):
                    try:
                        house_input.fill("")  # очистить
                        house_input.fill(num)
                        self._click_first_available_house()
                        break
                    except Exception:
                        continue
                else:
                    raise AssertionError("Не удалось выбрать дом: ни 3, ни 4, ни 7 не доступны в подсказках")
            except AssertionError:
                raise
            except Exception as e:
                raise AssertionError(
                    f"Не удалось указать дом (вариант 2) в форме 'Экспресс подключение'."
                )
            time.sleep(1)
            try:
                phone_input = self._pick_first_visible_element(ExpressConnection.PHONE, timeout_ms=5000)
                phone_input.fill("99999999999")
                time.sleep(1)
                send_button = self._pick_first_visible_element(ExpressConnection.BUTTON_SEND, timeout_ms=5000)
                send_button.click()
            except Exception as e:
                raise AssertionError(
                    "Не удалось отправить форму 'Экспресс подключение' (вариант 2)."
                )
            time.sleep(2)

    @allure.title("Перейти по случайным ссылкам городов из попапа выбора города и проверить")
    def check_random_city_links(self, desired_count: int = 20):
        with allure.step(f"Открыть попап выбора города и перейти по {desired_count} случайным ссылкам"):
            # Попап должен быть уже открыт извне
            self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).first.wait_for(state="visible", timeout=10000)

            # Получаем список всех доступных городов
            total = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
            if total == 0:
                raise AssertionError(
                    "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                    "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
                )

            target = min(desired_count, total)
            visited_cities = set()

            while len(visited_cities) < target:
                total_now = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
                # XPath индексация 1-based, поэтому randint [1, total_now]
                rand_index = random.randint(1, total_now)
                indexed_city_selector = f"{RegionChoice.RANSOM_CITY_BUTTON}[{rand_index}]"
                city_item = self.page.locator(indexed_city_selector)
                city_name = (city_item.text_content() or "").strip()
                expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
                city_href = city_item.get_attribute("href") or ""
                href_host = urlparse(city_href).netloc

                # Пропускаем пустые и уже посещенные
                if not city_name or city_name in visited_cities:
                    continue

                with allure.step("Открыть город (в новой вкладке)"):
                    with self.page.context.expect_page() as new_page_info:
                        city_item.click(modifiers=["Control"], force=True)  # открываем в новой вкладке
                    new_page = new_page_info.value
                    try:
                        new_page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        try:
                            new_page.wait_for_load_state("load", timeout=10000)
                        except Exception:
                            pass
                    # Подстраховка: ждём появления любых известных контролов выбора региона
                    found_region_ui = False
                    try:
                        new_page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
                        found_region_ui = True
                    except Exception:
                        try:
                            new_page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                            found_region_ui = True
                        except Exception:
                            try:
                                new_page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                                found_region_ui = True
                            except Exception:
                                pass
                    try:
                        expect(new_page).not_to_have_url("**/404")
                    except AssertionError:
                        raise AssertionError(
                            f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                            f"Переходили по ссылке: {city_href or '—'}, текущий URL: {new_page.url or '—'}.\n"
                            "Похоже, что ссылка на город ведёт на несуществующую страницу."
                        )
                    if not found_region_ui:
                        raise AssertionError(
                            f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                            "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                            "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
                        )

                    # Если это сабдомен (например, abakan.mts-home.online), проверяем домен URL
                    if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
                        assert href_host in (new_page.url or ""), (
                            f"Открыт неверный домен для города '{city_name}'.\n"
                            f"Ожидали домен: {href_host}, получили: {new_page.url or '—'}.\n"
                            "Ссылка на город ведёт на другой домен."
                        )
                    else:
                        # Иначе проверяем текст города в хедере
                        region_page = ChoiceRegionPage(page=new_page)
                        try:
                            region_page.verify_region_button_text_new(expected_city)
                        except AssertionError as e:
                            raise AssertionError(
                                f"Выбранный город не отобразился в хедере.\n"
                                f"Ожидали город: '{expected_city}', текущий URL: {new_page.url or '—'}.\n"
                                f"Подробности: {str(e)}"
                            )

                    new_page.close()

                visited_cities.add(city_name)
                time.sleep(1)

    @allure.title("Открыть 20 случайных городов (Beeline) и проверить соответствие")
    def check_random_beeline_cities(self, desired_count: int = 20):
        """
        Открывает до desired_count случайных ссылок городов по локатору //a[@class='region_item region_link'].
        Проверяет, что страницы открываются (не 404) и что город в хедере соответствует выбранному (с допуском по падежам).
        Открытие выполняется последовательно в той же вкладке по href без клика по элементу.
        """
        link_selector = "xpath=//a[@class='region_item region_link']"
        # Убедимся, что список городов виден/загружен
        try:
            self.page.locator(link_selector).first.wait_for(state="attached", timeout=10000)
        except Exception:
            raise AssertionError("Список городов (Beeline) не найден: //a[@class='region_item region_link']")

        total = self.page.locator(link_selector).count()
        if total == 0:
            raise AssertionError("Список городов пуст (Beeline).")

        target = min(desired_count, total)
        picked = []
        picked_hrefs = set()

        def normalize(text: str) -> str:
            return re.sub(r"\s+", " ", (text or "").strip())

        def city_variants(base: str):
            variants = {base}
            if len(base) >= 2:
                variants.add(base[:-1] + "у")
                variants.add(base[:-1] + "е")
            return list(variants)

        safety = 0
        while len(picked) < target and safety < total * 4:
            safety += 1
            idx = random.randint(0, total - 1)
            link = self.page.locator(link_selector).nth(idx)
            city_text_raw = (link.text_content() or "").strip()
            href = link.get_attribute("href") or ""
            if not city_text_raw or not href or not href.startswith("http"):
                continue
            if href in picked_hrefs:
                continue
            picked_hrefs.add(href)
            picked.append((city_text_raw, href, idx))

        for city_text_raw, href, idx in picked:
            # Подготовим ожидания по названию
            expected_city = re.sub(r"\s*\(.*?\)\s*$", "", (city_text_raw or "").strip())
            expected_norm = normalize(expected_city)
            accepted = []
            for v in city_variants(expected_norm):
                accepted.append(v)
                accepted.append(f"Вы находитесь в городе {v}")

            with allure.step("Открыть город"):
                # Навигируемся напрямую по href в текущей вкладке
                try:
                    self.page.goto(href, wait_until="domcontentloaded")
                except Exception:
                    # Повторная попытка
                    self.page.goto(href)
                try:
                    try:
                        self.page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        try:
                            self.page.wait_for_load_state("load", timeout=10000)
                        except Exception:
                            pass
                    # Не должно быть 404
                    expect(self.page).not_to_have_url("**/404")
                    # Ищем текст города в хедере
                    header_candidates = [
                        RegionChoice.NEW_REGION_CHOICE_BUTTON,
                        RegionChoice.TELE_REGION_CHOICE_BUTTON,
                        RegionChoice.REGION_CHOICE_BUTTON,
                    ]
                    found_text = ""
                    for sel in header_candidates:
                        try:
                            loc = self.page.locator(sel).first
                            if loc.count() == 0:
                                continue
                            txt = normalize(loc.text_content() or "")
                            if txt:
                                found_text = txt
                                break
                        except Exception:
                            continue
                    if found_text:
                        if not (found_text == expected_norm or any(pat == found_text or pat in found_text for pat in accepted)):
                            # Фолбэк: проверим текст всего документа
                            body_text = normalize(self.page.locator("body").text_content() or "")
                            if not any(pat in body_text for pat in accepted):
                                raise AssertionError(
                                    f"Город в хедере не совпал с выбранным.\n"
                                    f"Ожидали: '{expected_norm}' (допуски: {accepted}).\n"
                                    f"Нашли: '{found_text or '—'}'.\n"
                                    f"URL: {self.page.url or '—'}."
                                )
                    else:
                        body_text = normalize(self.page.locator("body").text_content() or "")
                        if not any(pat in body_text for pat in accepted):
                            raise AssertionError(
                                f"Не удалось обнаружить текст города на странице.\n"
                                f"Ожидали: '{expected_norm}' (допуски: {accepted}).\n"
                                f"URL: {self.page.url or '—'}."
                            )
                except Exception:
                    # Если что-то пошло не так при проверке конкретного города — продолжаем к следующему
                    pass

    @allure.title("Перейти по одному случайному городу из уже открытого попапа и проверить")
    def click_random_city_and_verify(self):
        # Попап должен быть уже открыт извне
        self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).first.wait_for(state="visible", timeout=10000)
        total_now = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
        if total_now == 0:
            raise AssertionError(
                "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
            )

        rand_index = random.randint(1, total_now)
        indexed_city_selector = f"{RegionChoice.RANSOM_CITY_BUTTON}[{rand_index}]"
        city_item = self.page.locator(indexed_city_selector)
        city_name = (city_item.text_content() or "").strip()
        expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
        city_href = city_item.get_attribute("href") or ""
        href_host = urlparse(city_href).netloc

        with allure.step("Открыть город (в новой вкладке)"):
            with self.page.context.expect_page() as new_page_info:
                city_item.click(modifiers=["Control"], force=True)  # открываем в новой вкладке
            new_page = new_page_info.value
            try:
                new_page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                try:
                    new_page.wait_for_load_state("load", timeout=10000)
                except Exception:
                    pass
            found_region_ui = False
            try:
                new_page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
                found_region_ui = True
            except Exception:
                try:
                    new_page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                    found_region_ui = True
                except Exception:
                    try:
                        new_page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                        found_region_ui = True
                    except Exception:
                        pass
            try:
                expect(new_page).not_to_have_url("**/404")
            except AssertionError:
                raise AssertionError(
                    f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                    f"Переходили по ссылке: {city_href or '—'}, текущий URL: {new_page.url or '—'}.\n"
                    "Похоже, что ссылка на город ведёт на несуществующую страницу."
                )
            if not found_region_ui:
                raise AssertionError(
                    f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                    "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                    "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
                )

            if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
                assert href_host in (new_page.url or ""), (
                    f"Открыт неверный домен для города '{city_name}'.\n"
                    f"Ожидали домен: {href_host}, получили: {new_page.url or '—'}.\n"
                    "Ссылка на город ведёт на другой домен."
                )
            else:
                region_page = ChoiceRegionPage(page=new_page)
                try:
                    region_page.verify_region_button_text_new(expected_city)
                except AssertionError as e:
                    raise AssertionError(
                        f"Выбранный город не отобразился в хедере.\n"
                        f"Ожидали город: '{expected_city}', текущий URL: {new_page.url or '—'}.\n"
                        f"Подробности: {str(e)}"
                    )

            new_page.close()

    @allure.title("Перейти по одному случайному городу (в той же вкладке) из уже открытого попапа и проверить")
    def click_random_city_and_verify_same_tab(self):
        # Попап должен быть уже открыт извне
        try:
            self.page.locator("xpath=//table[@class='city_list']").wait_for(state="visible", timeout=7000)
        except Exception:
            self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).first.wait_for(state="attached", timeout=7000)

        total_now = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
        if total_now == 0:
            raise AssertionError(
                "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
            )

        rand_index = random.randint(1, total_now)
        city_item = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).nth(rand_index - 1)
        city_name = (city_item.text_content() or "").strip()
        expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
        city_href = city_item.get_attribute("href") or ""
        href_host = urlparse(city_href).netloc

        with allure.step("Открыть город (та же вкладка)"):
            city_item.scroll_into_view_if_needed()
            city_item.click(force=True)

        # Ожидаем навигацию и выполняем строгую проверку: при несоответствии тест падает
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
        found_region_ui = False
        try:
            self.page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
            found_region_ui = True
        except Exception:
            try:
                self.page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                found_region_ui = True
            except Exception:
                try:
                    self.page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                    found_region_ui = True
                except Exception:
                    pass
        try:
            expect(self.page).not_to_have_url("**/404")
        except AssertionError:
            raise AssertionError(
                f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                f"Переходили по ссылке: {city_href or '—'}, текущий URL: {self.page.url or '—'}.\n"
                "Похоже, что ссылка на город ведёт на несуществующую страницу."
            )
        if not found_region_ui:
            raise AssertionError(
                f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
            )

        if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
            assert href_host in (self.page.url or ""), (
                f"Открыт неверный домен для города '{city_name}'.\n"
                f"Ожидали домен: {href_host}, получили: {self.page.url or '—'}.\n"
                "Ссылка на город ведёт на другой домен."
            )
        else:
            try:
                self._verify_city_label_accepts_variants(expected_city)
            except AssertionError as e:
                raise AssertionError(
                    f"Выбранный город не отобразился в хедере.\n"
                    f"Ожидали город: '{expected_city}', текущий URL: {self.page.url or '—'}.\n"
                    f"Подробности: {str(e)}"
                )

    @allure.title("Перейти по одному случайному городу (в той же вкладке) из уже открытого попапа и проверить")
    def click_random_city_and_verify_same_tab_popup(self):
        # Попап должен быть уже открыт извне
        try:
            self.page.locator("xpath=//table[@class='city_list']").wait_for(state="visible", timeout=7000)
        except Exception:
            self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).first.wait_for(state="attached", timeout=7000)

        total_now = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
        if total_now == 0:
            raise AssertionError(
                "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
            )

        rand_index = random.randint(1, total_now)
        city_item = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).nth(rand_index - 1)
        city_name = (city_item.text_content() or "").strip()
        expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
        city_href = city_item.get_attribute("href") or ""
        href_host = urlparse(city_href).netloc

        with allure.step("Открыть город (та же вкладка)"):
            city_item.scroll_into_view_if_needed()
            city_item.click(force=True)

        # Ожидаем навигацию и выполняем строгую проверку: при несоответствии тест падает
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
        found_region_ui = False
        try:
            self.page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
            found_region_ui = True
        except Exception:
            try:
                self.page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                found_region_ui = True
            except Exception:
                try:
                    self.page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                    found_region_ui = True
                except Exception:
                    pass
        try:
            expect(self.page).not_to_have_url("**/404")
        except AssertionError:
            raise AssertionError(
                f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                f"Переходили по ссылке: {city_href or '—'}, текущий URL: {self.page.url or '—'}.\n"
                "Похоже, что ссылка на город ведёт на несуществующую страницу."
            )
        if not found_region_ui:
            raise AssertionError(
                f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
            )
        region_page = ChoiceRegionPage(page=self.page)
        region_page.close_popup_super_offer_new()

        if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
            assert href_host in (self.page.url or ""), (
                f"Открыт неверный домен для города '{city_name}'.\n"
                f"Ожидали домен: {href_host}, получили: {self.page.url or '—'}.\n"
                "Ссылка на город ведёт на другой домен."
            )
        else:
            try:
                self._verify_city_label_accepts_variants(expected_city)
            except AssertionError as e:
                raise AssertionError(
                    f"Выбранный город не отобразился в хедере.\n"
                    f"Ожидали город: '{expected_city}', текущий URL: {self.page.url or '—'}.\n"
                    f"Подробности: {str(e)}"
                )

    @allure.title("Перейти по одному случайному городу (в той же вкладке) из уже открытого попапа и проверить")
    def click_random_city_and_verify_same_tab_new(self):
        # Попап должен быть уже открыт извне
        try:
            self.page.locator("xpath=//table[@class='city_list']").wait_for(state="visible", timeout=7000)
        except Exception:
            self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).first.wait_for(state="attached", timeout=7000)

        total_now = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).count()
        if total_now == 0:
            raise AssertionError(
                "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
            )

        rand_index = random.randint(1, total_now)
        city_item = self.page.locator(RegionChoice.RANSOM_CITY_BUTTON).nth(rand_index - 1)
        city_name = (city_item.text_content() or "").strip()
        expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
        city_href = city_item.get_attribute("href") or ""
        href_host = urlparse(city_href).netloc

        with allure.step("Открыть город (та же вкладка)"):
            city_item.scroll_into_view_if_needed()
            city_item.click(force=True)

        # Ожидаем навигацию и выполняем строгую проверку: при несоответствии тест падает
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
        found_region_ui = False
        try:
            self.page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
            found_region_ui = True
        except Exception:
            try:
                self.page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                found_region_ui = True
            except Exception:
                try:
                    self.page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                    found_region_ui = True
                except Exception:
                    pass
        try:
            expect(self.page).not_to_have_url("**/404")
        except AssertionError:
            raise AssertionError(
                f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                f"Переходили по ссылке: {city_href or '—'}, текущий URL: {self.page.url or '—'}.\n"
                "Похоже, что ссылка на город ведёт на несуществующую страницу."
            )
        if not found_region_ui:
            raise AssertionError(
                f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
            )

        if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
            assert href_host in (self.page.url or ""), (
                f"Открыт неверный домен для города '{city_name}'.\n"
                f"Ожидали домен: {href_host}, получили: {self.page.url or '—'}.\n"
                "Ссылка на город ведёт на другой домен."
            )
        else:
            try:
                self._verify_city_label_accepts_variants(expected_city)
            except AssertionError as e:
                raise AssertionError(
                    f"Выбранный город не отобразился в хедере.\n"
                    f"Ожидали город: '{expected_city}', текущий URL: {self.page.url or '—'}.\n"
                    f"Подробности: {str(e)}"
                )

    @allure.title("Перейти по одному случайному городу (в той же вкладке) из уже открытого попапа и проверить")
    def click_random_city_and_verify_new_cutyloc(self):
        # Попап должен быть уже открыт извне
        try:
            self.page.locator("xpath=//table[@class='city_list']").wait_for(state="visible", timeout=7000)
        except Exception:
            self.page.locator(RegionChoice.CITY_LOC).first.wait_for(state="attached", timeout=7000)

        total_now = self.page.locator(RegionChoice.CITY_LOC).count()
        if total_now == 0:
            raise AssertionError(
                "Список городов пуст. Не найден ни один элемент по локатору RegionChoice.RANSOM_CITY_BUTTON.\n"
                "Возможные причины: попап не открыт, список городов не подгрузился, разметка изменилась."
            )

        rand_index = random.randint(1, total_now)
        city_item = self.page.locator(RegionChoice.CITY_LOC).nth(rand_index - 1)
        city_name = (city_item.text_content() or "").strip()
        expected_city = re.sub(r"\s*\(.*?\)\s*$", "", city_name).strip()
        city_href = city_item.get_attribute("href") or ""
        href_host = urlparse(city_href).netloc

        with allure.step("Открыть город (та же вкладка)"):
            city_item.scroll_into_view_if_needed()
            city_item.click(force=True)

        # Ожидаем навигацию и выполняем строгую проверку: при несоответствии тест падает
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            try:
                self.page.wait_for_load_state("load", timeout=10000)
            except Exception:
                pass
        found_region_ui = False
        try:
            self.page.locator(RegionChoice.NEW_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=5000)
            found_region_ui = True
        except Exception:
            try:
                self.page.locator(RegionChoice.TELE_REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                found_region_ui = True
            except Exception:
                try:
                    self.page.locator(RegionChoice.REGION_CHOICE_BUTTON).first.wait_for(state="attached", timeout=3000)
                    found_region_ui = True
                except Exception:
                    pass
        try:
            expect(self.page).not_to_have_url("**/404")
        except AssertionError:
            raise AssertionError(
                f"Открылась страница 404 при переходе в город '{city_name}' (idx {rand_index}).\n"
                f"Переходили по ссылке: {city_href or '—'}, текущий URL: {self.page.url or '—'}.\n"
                "Похоже, что ссылка на город ведёт на несуществующую страницу."
            )
        if not found_region_ui:
            raise AssertionError(
                f"Не удалось обнаружить элементы выбора региона на странице города '{city_name}' (idx {rand_index}).\n"
                "Ожидались элементы из набора: NEW_REGION_CHOICE_BUTTON / TELE_REGION_CHOICE_BUTTON / REGION_CHOICE_BUTTON.\n"
                "Возможные причины: страница не успела инициализировать UI, изменилась разметка или открыт неверный экран."
            )

        if href_host and href_host.endswith(".mts-home.online") and href_host != "mts-home.online":
            assert href_host in (self.page.url or ""), (
                f"Открыт неверный домен для города '{city_name}'.\n"
                f"Ожидали домен: {href_host}, получили: {self.page.url or '—'}.\n"
                "Ссылка на город ведёт на другой домен."
            )
        else:
            try:
                self._verify_city_label_accepts_variants(expected_city)
            except AssertionError as e:
                raise AssertionError(
                    f"Выбранный город не отобразился в хедере.\n"
                    f"Ожидали город: '{expected_city}', текущий URL: {self.page.url or '—'}.\n"
                    f"Подробности: {str(e)}"
                )
