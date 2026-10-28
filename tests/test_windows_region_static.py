"""Windows 地区自适应 / set-region 静态回归(不执行 PowerShell,可在 macOS CI 运行)。"""
import unittest
from pathlib import Path

try:
    from test_windows_update_static import ps1_balance_error
except ImportError:
    from tests.test_windows_update_static import ps1_balance_error


ROOT = Path(__file__).resolve().parents[1]
WIN = ROOT / "windows"
CORE = WIN / "claude-switch.ps1"
UI = WIN / "SwitcherUI.ps1"
INSTALL = WIN / "install.ps1"
README = WIN / "README.md"
AGENTS = ROOT / "AGENTS.md"
PS1_FILES = (CORE, UI, INSTALL, WIN / "claude-bodyguard.ps1")


def read(path):
    return path.read_text(encoding="utf-8-sig")


def between(text, start_marker, end_marker):
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class WindowsRegionStaticTests(unittest.TestCase):
    def test_ps1_bom_and_lexical_balance(self):
        for path in PS1_FILES:
            with self.subTest(path=path.name):
                self.assertTrue(
                    path.read_bytes().startswith(b"\xef\xbb\xbf"),
                    f"{path.name} 必须保持 UTF-8 with BOM",
                )
                self.assertIsNone(ps1_balance_error(read(path)), path.name)

    def test_locale_target_header_and_region_check(self):
        text = read(CORE)
        self.assertIn('$LOCALE_TARGET = "en-US"', text)
        self.assertIn("[System.Globalization.CultureInfo]::CurrentCulture.Name", text)
        self.assertIn('"地区=ok:$cult"', text)
        self.assertIn('"地区=fail:$cult(期望$LOCALE_TARGET)"', text)
        self.assertNotIn("$cult -eq 'en-US'", text)

        start = text.index("$cult = [System.Globalization.CultureInfo]::CurrentCulture.Name")
        block = text[start : start + 300]
        self.assertNotIn("en-US", block, "地区检查不能写死 en-US")

    def test_clash_mode_fallback_includes_config_yaml(self):
        text = read(CORE)
        body = between(text, "function Get-ClashMode", "function Get-ClashRules")
        self.assertIn(
            "@('clash-verge.yaml', 'config.yaml', 'verge.yaml')", body
        )

    def test_update_now_preserves_five_configs(self):
        text = read(CORE)
        body = between(text, "function Invoke-UpdateNow", "switch ($args[0])")
        self.assertIn("5 项用户配置", body)
        for name in (
            "PROXY_MODE",
            "COUNTRY_TARGET",
            "TZ_TARGET",
            "LOCALE_TARGET",
            "PROXY_GROUP",
        ):
            with self.subTest(name=name):
                self.assertIn(f"'{name}'", body)

    def test_set_region_command_and_dispatch(self):
        text = read(CORE)
        self.assertIn("function Invoke-SetRegion", text)
        self.assertIn("'set-region'   { Invoke-SetRegion }", text)
        self.assertIn("set-region|check-update|update-now", text)

        body = between(text, "function Invoke-SetRegion", "# STUN 探针")
        for needle in (
            "FAIL:所有出口探测源均失败",
            "HINT:请检查代理规则/稍后重试",
            "FAIL:出口国家为 CN,已中止",
            "Set-ScriptConfigValue $text 'COUNTRY_TARGET'",
            "Set-ScriptConfigValue $text 'TZ_TARGET'",
            "Set-ScriptConfigValue $text 'LOCALE_TARGET'",
            "UTF8Encoding($true)",
            "Start-Process powershell -Verb RunAs -Wait",
            "Set-TimeZone -Id",
            "if ((Get-TimeZone).Id -ne '$tzEsc') { exit 1 }",
            "Set-Culture -CultureInfo $locale",
            "WARN:时区未修改,请手动设置",
            "WARN:地区格式未修改,请手动在「区域格式」中修改",
            "OK:region=$country tz=$ianaTz locale=$locale source=$($geo.Source)",
            "INFO:时区使用国家默认(可手动改)",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, body)

    def test_country_timezone_and_locale_maps(self):
        text = read(CORE)
        timezones = {
            "US": "America/New_York",
            "JP": "Asia/Tokyo",
            "TW": "Asia/Taipei",
            "HK": "Asia/Hong_Kong",
            "SG": "Asia/Singapore",
            "GB": "Europe/London",
            "DE": "Europe/Berlin",
            "FR": "Europe/Paris",
            "KR": "Asia/Seoul",
            "AU": "Australia/Sydney",
            "CA": "America/Toronto",
            "MY": "Asia/Kuala_Lumpur",
        }
        locales = {
            "US": "en-US",
            "JP": "ja-JP",
            "TW": "zh-TW",
            "HK": "zh-HK",
            "SG": "en-SG",
            "GB": "en-GB",
            "DE": "de-DE",
            "FR": "fr-FR",
            "KR": "ko-KR",
            "AU": "en-AU",
            "CA": "en-CA",
            "MY": "ms-MY",
        }
        for cc, tz in timezones.items():
            with self.subTest(country=cc):
                self.assertIn(f"'{cc}' = '{tz}'", text)
        for cc, locale in locales.items():
            with self.subTest(country=cc, locale=locale):
                self.assertIn(f"'{cc}' = '{locale}'", text)
        self.assertIn("function Get-CountryDefaultTimeZone", text)
        self.assertIn("function Get-CountryLocale", text)
        self.assertIn("return 'America/New_York'", text)
        self.assertIn("return 'en-US'", text)
        self.assertIn("function ConvertTo-WindowsTimeZone", text)
        self.assertRegex(
            text, r"'Asia/Kuala_Lumpur'\s*=\s*'Singapore Standard Time'"
        )

    def test_get_geo_info_multi_source(self):
        text = read(CORE)
        body = between(text, "function Get-GeoInfo", "function Invoke-SetRegion")
        for url in (
            "https://ipinfo.io/json",
            "https://ipapi.co/json/",
            "https://ifconfig.co/json",
            "https://www.cloudflare.com/cdn-cgi/trace",
        ):
            with self.subTest(url=url):
                self.assertIn(url, body)
        self.assertIn("[Net.SecurityProtocolType]::Tls12", body)
        self.assertIn("TimeoutSec 8", body)
        self.assertIn("-UserAgent $ua", body)
        self.assertIn("TimezoneDefault = $firstTzDefault", body)
        self.assertIn("Diagnostics = ($diag -join '; ')", body)

    def test_installer_sets_locale_and_supports_my(self):
        text = read(INSTALL)
        self.assertIn("$countryLocale = @{", text)
        self.assertIn("$LOCALE_TARGET = $countryLocale[$country]", text)
        self.assertIn('LOCALE_TARGET = "[^"]*"', text)
        self.assertIn("Set-Culture -CultureInfo $LOCALE_TARGET", text)
        self.assertIn("'MY' = 'Asia/Kuala_Lumpur'", text)
        self.assertIn("'MY' = 'ms-MY'", text)
        self.assertIn("function ConvertTo-WindowsTimeZone", text)
        self.assertRegex(
            text, r"'Asia/Kuala_Lumpur'\s*=\s*'Singapore Standard Time'"
        )

    def test_installer_uses_user_agent_parameter(self):
        for path in (CORE, INSTALL):
            text = read(path)
            with self.subTest(path=path.name):
                self.assertNotIn("'User-Agent' =", text)
                self.assertIn("-UserAgent $ua", text)

    def test_readme_and_agents_cover_set_region(self):
        readme = read(README)
        self.assertIn("## 地区自适应与 set-region", readme)
        for needle in (
            "set-region",
            "LOCALE_TARGET",
            "CN",
            "不会每次检查自动跟随",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, readme)
        self.assertNotIn("地区检查目前仍固定为 en-US", readme)
        self.assertNotIn("Windows 版暂无 `set-region`", readme)

        agents = read(AGENTS)
        self.assertIn("Windows 地区检查误红", agents)
        self.assertIn("set-region", agents)
        self.assertIn("LOCALE_TARGET", agents)


if __name__ == "__main__":
    unittest.main()
