"""install_basic.sh 一键安装流程验证测试.

验证非技术人员使用的安装脚本正确性，覆盖：
  1. bash 语法正确性（bash -n）
  2. 许可证密钥格式校验正则表达式正确
  3. 脚本不包含硬编码敏感信息（生产 IP、密码、API Key）
  4. 生成的 .env.basic 模板包含必要配置项
  5. 生成的 docker-compose.yml 模板格式正确

设计原则：
  - 不执行脚本（避免 Docker 依赖），只做静态验证
  - 验证用户第一接触点的正确性，降低非技术用户安装失败率
"""

import re
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "install_basic.sh"


@pytest.fixture(scope="module")
def script_content() -> str:
    """读取 install_basic.sh 全文."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


# ── 1. bash 语法正确性 ──────────────────────────────────────────


class TestBashSyntax:
    """验证 install_basic.sh 的 bash 语法正确."""

    def test_bash_syntax_valid(self):
        """bash -n 检查脚本语法（不执行）."""
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash 语法错误:\n{result.stderr}"

    def test_script_has_shebang(self, script_content: str):
        """脚本第一行必须有 shebang."""
        assert script_content.startswith("#!/bin/bash"), "缺少 #!/bin/bash shebang"

    def test_script_uses_set_e(self, script_content: str):
        """脚本必须 set -e（出错即退出）."""
        assert "set -e" in script_content, "缺少 set -e，出错不会退出"


# ── 2. 许可证密钥格式校验 ──────────────────────────────────────


class TestLicenseKeyValidation:
    """验证许可证密钥格式校验逻辑."""

    def test_license_regex_exists(self, script_content: str):
        """脚本必须包含许可证密钥正则校验."""
        # PL-PRO-xxxx-xxxx-xxxx 格式
        pattern = r"PL-PRO-\[a-zA-Z0-9\]"
        assert re.search(pattern, script_content), "缺少许可证密钥正则校验"

    def test_license_format_correct(self, script_content: str):
        """正则表达式必须匹配正确的格式."""
        # 提取脚本中的正则表达式
        match = re.search(r"\^PL-PRO-\[a-zA-Z0-9\]\{4\}-\[a-zA-Z0-9\]\{4\}-\[a-zA-Z0-9\]\{4,\}\$", script_content)
        assert match, "许可证密钥正则格式不正确"

    @pytest.mark.parametrize("key,valid", [
        ("PL-PRO-aaaa-bbbb-cccc", True),
        ("PL-PRO-A1B2-C3D4-E5F6", True),
        ("PL-PRO-aaaa-bbbb-ccccc", True),  # {4,} 允许第三段超过4位
        ("PL-PRO-aaaa-bbbb-cccc-dddd", False),  # 4段格式不匹配（正则是3段）
        ("pl-pro-aaaa-bbbb-cccc", False),  # 小写前缀
        ("PL-PRO-aaa-bbbb-cccc", False),  # 第一段不足4位
        ("PL-PRO-aaaa-bbb-cccc", False),  # 第二段不足4位
        ("PL-PRO-aaaa-bbbb-ccc", False),  # 第三段不足4位
        ("INVALID-KEY", False),
        ("", False),
    ])
    def test_license_key_format(self, key: str, valid: bool):
        """参数化测试许可证密钥格式."""
        regex = re.compile(r"^PL-PRO-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4,}$")
        matched = bool(regex.match(key))
        assert matched == valid, f"key='{key}' expected valid={valid} but got {matched}"


# ── 3. 脚本不包含硬编码敏感信息 ────────────────────────────────


class TestNoHardcodedSecrets:
    """验证脚本不包含硬编码的敏感信息（仓库公开前置条件）."""

    SENSITIVE_IP_PATTERN = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

    def test_no_hardcoded_production_ip(self, script_content: str):
        """脚本不得包含硬编码的生产 IP 地址."""
        # 排除 127.0.0.1 和 0.0.0.0（这些是本地地址，可以保留）
        ips = self.SENSITIVE_IP_PATTERN.findall(script_content)
        dangerous_ips = [ip for ip in ips if ip not in ("127.0.0.1", "0.0.0.0")]
        assert not dangerous_ips, f"发现硬编码 IP: {dangerous_ips}"

    def test_no_hardcoded_api_key(self, script_content: str):
        """脚本不得包含硬编码的 API Key."""
        # 检查常见的 API Key 模式
        key_patterns = [
            r"sk-[a-zA-Z0-9]{20,}",  # OpenAI 风格
            r"pl-pro-[a-zA-Z0-9]{20,}",  # PromiseLink Pro Key
            r"TAO_APP_PRO_API_KEY\s*=\s*['\"]\w",  # 直接赋值
        ]
        for pattern in key_patterns:
            assert not re.search(pattern, script_content), f"发现硬编码 API Key 模式: {pattern}"

    def test_no_hardcoded_password(self, script_content: str):
        """脚本不得包含硬编码的密码."""
        # 排除占位符和提示文字
        password_patterns = [
            r"POSTGRES_PASSWORD\s*=\s*['\"]\w",
            r"PG_PASSWORD\s*=\s*['\"]\w",
        ]
        for pattern in password_patterns:
            assert not re.search(pattern, script_content), f"发现硬编码密码模式: {pattern}"

    def test_gateway_url_uses_env_var(self, script_content: str):
        """网关地址必须通过环境变量配置."""
        # 检查 DEFAULT_GATEWAY_URL 使用 ${GATEWAY_URL:-...} 格式
        assert "${GATEWAY_URL:-" in script_content, "网关地址未使用环境变量优先配置"


# ── 4. 生成的 .env.basic 模板验证 ──────────────────────────────


class TestEnvBasicTemplate:
    """验证脚本生成的 .env.basic 模板包含必要配置项."""

    def test_env_basic_has_required_vars(self, script_content: str):
        """.env.basic 模板必须包含所有必要配置项."""
        required_vars = [
            "APP_ENV",
            "DATABASE_URL",
            "SECRET_KEY",
            "POC_SECRET",
            "RELAY_GATEWAY_URL",
            "PRO_LICENSE_KEY",
            "RELAY_WSS_ENABLED",
            "RELAY_LOCAL_API_URL",
        ]
        for var in required_vars:
            assert var in script_content, f".env.basic 模板缺少必要配置项: {var}"

    def test_secret_key_auto_generated(self, script_content: str):
        """SECRET_KEY 必须自动生成（非硬编码）."""
        # 检查脚本使用 secrets.token_urlsafe 或 openssl rand 生成 SECRET_KEY
        assert "secrets.token_urlsafe" in script_content or "openssl rand" in script_content, \
            "SECRET_KEY 未自动生成"

    def test_poc_secret_auto_generated(self, script_content: str):
        """POC_SECRET 必须自动生成（非硬编码默认值）."""
        # 检查 POC_SECRET 使用 openssl rand 生成
        assert "openssl rand" in script_content, "POC_SECRET 未自动生成"


# ── 5. 生成的 docker-compose.yml 模板验证 ──────────────────────


class TestDockerComposeTemplate:
    """验证脚本生成的 docker-compose.yml 模板格式正确."""

    def test_compose_template_has_required_services(self, script_content: str):
        """docker-compose.yml 模板必须包含 promiselink-api 服务."""
        assert "promiselink-api" in script_content, "缺少 promiselink-api 服务定义"

    def test_compose_template_has_healthcheck(self, script_content: str):
        """docker-compose.yml 模板必须包含健康检查."""
        assert "healthcheck" in script_content, "缺少健康检查配置"
        assert "/api/v1/health" in script_content, "健康检查端点不正确"

    def test_compose_template_has_volume(self, script_content: str):
        """docker-compose.yml 模板必须包含数据卷挂载."""
        assert "./data:/data" in script_content, "缺少数据卷挂载"

    def test_compose_template_has_restart_policy(self, script_content: str):
        """docker-compose.yml 模板必须包含重启策略."""
        assert "restart:" in script_content, "缺少重启策略"

    def test_compose_template_has_logging(self, script_content: str):
        """docker-compose.yml 模板必须包含日志轮转配置."""
        assert "max-size" in script_content, "缺少日志大小限制"
        assert "max-file" in script_content, "缺少日志文件数限制"


# ── 6. 用户引导信息验证 ────────────────────────────────────────


class TestUserGuidance:
    """验证脚本对非技术用户的引导信息完整性."""

    def test_has_docker_check(self, script_content: str):
        """脚本必须检查 Docker 是否安装."""
        assert "command -v docker" in script_content, "缺少 Docker 安装检查"

    def test_has_docker_running_check(self, script_content: str):
        """脚本必须检查 Docker 是否运行."""
        assert "docker info" in script_content, "缺少 Docker 运行状态检查"

    def test_has_health_check_wait(self, script_content: str):
        """脚本必须等待服务健康检查通过."""
        assert "health" in script_content.lower(), "缺少健康检查等待逻辑"

    def test_has_completion_message(self, script_content: str):
        """脚本必须有完成提示信息."""
        assert "安装完成" in script_content, "缺少安装完成提示"

    def test_has_support_contact(self, script_content: str):
        """脚本必须包含支持联系方式."""
        assert "support@promiselink.cn" in script_content, "缺少支持联系方式"

    def test_has_common_commands(self, script_content: str):
        """脚本必须包含常用命令说明."""
        commands = ["docker compose logs", "docker compose down", "docker compose up"]
        for cmd in commands:
            assert cmd in script_content, f"缺少常用命令说明: {cmd}"

    def test_has_backup_guidance(self, script_content: str):
        """脚本必须包含数据备份指导."""
        assert "备份" in script_content, "缺少数据备份指导"
