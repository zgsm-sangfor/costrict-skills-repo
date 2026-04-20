"""Regression checks for VSCode Costrict install/update path consistency."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class TestVscodeInstallConsistency(unittest.TestCase):
    def _read(self, rel_path: str) -> str:
        path = ROOT / rel_path
        self.assertTrue(path.exists(), f"File not found: {rel_path}")
        return path.read_text(encoding="utf-8")

    def test_readme_vscode_fallback_install_uses_global_roo_commands(self):
        content = self._read("README.md")
        self.assertIn("mkdir -p ~/.roo/commands", content)
        self.assertIn("~/.roo/commands/eac-${cmd}.md", content)
        self.assertNotIn("无需安装子命令", content)

    def test_shell_installer_uses_global_roo_commands_for_vscode(self):
        content = self._read("install.sh")
        self.assertIn('local cmd_dir="$home_dir/.roo/commands"', content)
        self.assertIn('Commands (global): $cmd_dir/', content)

    def test_powershell_installer_downloads_vscode_commands_to_global_dir(self):
        content = self._read("install.ps1")
        self.assertIn('$cmdDir = Join-Path $HOME ".roo/commands"', content)
        self.assertIn('Downloading commands (global)...', content)
        self.assertIn('eac-$cmd.md', content)

    def test_vscode_skill_describes_update_command(self):
        content = self._read("platforms/vscode-costrict/skills/eac/SKILL.md")
        self.assertIn("### update", content)
        self.assertIn("Pull latest version", content)

    def test_vscode_update_command_uses_global_roo_commands(self):
        content = self._read("platforms/vscode-costrict/commands/eac/eac-update.md")
        self.assertIn("mkdir -p $HOME/.roo/commands", content)
        self.assertIn('"$HOME/.roo/commands/eac-${cmd}.md"', content)


if __name__ == "__main__":
    unittest.main()
