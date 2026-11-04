using System;
using System.Drawing;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        if (args.Length == 1 && args[0] == "--self-test")
        {
            try
            {
                if (String.IsNullOrEmpty(LauncherForm.HelperBase64())) return 2;
                using (var form = new LauncherForm()) { return form.Controls.Count >= 5 ? 0 : 3; }
            }
            catch { return 4; }
        }
        if (args.Length == 1 && args[0] == "--check-status")
        {
            try
            {
                using (var form = new LauncherForm())
                {
                    string result = form.Helper("status");
                    return result == "RUNNING" ? 10 : (result == "STOPPED" ? 11 : 12);
                }
            }
            catch { return 12; }
        }
        bool created;
        using (var mutex = new Mutex(true, @"Local\WeChatBotController_Public", out created))
        {
            if (!created)
            {
                MessageBox.Show("控制窗口已经打开。", "微信机器人", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return 0;
            }
            Application.Run(new LauncherForm());
        }
        return 0;
    }
}

internal sealed class LauncherForm : Form
{
    private readonly string root;
    private readonly string python;
    private readonly string bot;
    private readonly string logPath;
    private readonly Label state;
    private readonly Label hint;
    private readonly Button start;
    private readonly Button stop;
    private readonly Button refresh;
    private readonly System.Windows.Forms.Timer timer;
    private bool busy;

    internal static string HelperBase64()
    {
        using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("bot_launcher_helper.py"))
        {
            if (stream == null) throw new InvalidOperationException("缺少运行组件。");
            using (var memory = new MemoryStream()) { stream.CopyTo(memory); return Convert.ToBase64String(memory.ToArray()); }
        }
    }

    internal LauncherForm()
    {
        Text = "微信机器人开关";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        ClientSize = new Size(520, 320);
        MinimumSize = new Size(536, 359);
        Font = new Font("Microsoft YaHei UI", 10F);
        BackColor = Color.FromArgb(247, 249, 252);

        string beside = AppDomain.CurrentDomain.BaseDirectory;
        string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        bool besideIsProject = File.Exists(Path.Combine(beside, "bot.py")) &&
            File.Exists(Path.Combine(beside, ".venv", "Scripts", "python.exe"));
        root = besideIsProject ? beside : Path.Combine(home, "wechat-ai-bot");
        python = Path.Combine(root, ".venv", "Scripts", "python.exe");
        bot = Path.Combine(root, "bot.py");
        logPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WeChatBotLauncher", "运行日志.log");

        var title = new Label { Text = "微信机器人", Font = new Font(Font.FontFamily, 18F, FontStyle.Bold), AutoSize = true, Location = new Point(27, 20) };
        Controls.Add(title);
        state = new Label { Text = "正在检查状态…", AutoSize = false, Location = new Point(30, 73), Size = new Size(460, 32), ForeColor = Color.FromArgb(51, 65, 85) };
        Controls.Add(state);
        start = MakeButton("启动机器人", 30, Color.FromArgb(21, 128, 82));
        stop = MakeButton("关闭机器人", 185, Color.FromArgb(176, 58, 48));
        refresh = MakeButton("刷新状态", 340, Color.FromArgb(72, 85, 101));
        Controls.Add(start); Controls.Add(stop); Controls.Add(refresh);
        hint = new Label { Text = "机器人在后台运行，不弹出命令行窗口。\n关闭机器人会中断当前任务，不会关闭微信。\n关闭本窗口不会停止机器人。", AutoSize = false, Location = new Point(31, 167), Size = new Size(465, 80), ForeColor = Color.FromArgb(90, 99, 111) };
        Controls.Add(hint);
        var log = new LinkLabel { Text = "查看运行日志", AutoSize = true, Location = new Point(31, 258) };
        log.LinkClicked += (s, e) => OpenLog();
        Controls.Add(log);
        start.Enabled = false; stop.Enabled = false;
        start.Click += async (s, e) => await StartBot();
        stop.Click += async (s, e) => await StopBot();
        refresh.Click += async (s, e) => await UpdateStatus();
        Shown += async (s, e) => await UpdateStatus();
        timer = new System.Windows.Forms.Timer { Interval = 10000 };
        timer.Tick += async (s, e) => await UpdateStatus();
        timer.Start();
        FormClosed += (s, e) => timer.Dispose();
    }

    private static Button MakeButton(string text, int x, Color color)
    {
        var button = new Button { Text = text, Location = new Point(x, 112), Size = new Size(142, 42), FlatStyle = FlatStyle.Flat, BackColor = color, ForeColor = Color.White, Cursor = Cursors.Hand };
        button.FlatAppearance.BorderSize = 0;
        return button;
    }

    internal string Helper(string action)
    {
        if (!File.Exists(python) || !File.Exists(bot)) return "MISSING";
        string code = "exec(__import__('base64').b64decode('" + HelperBase64() + "'))";
        var info = new ProcessStartInfo(python, "-X utf8 -c \"" + code + "\" " + action);
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        using (Process process = Process.Start(info))
        {
            if (process == null) return "UNKNOWN";
            // The helper produces only one short status line.
            if (!process.WaitForExit(10000)) { try { process.Kill(); } catch { } return "UNKNOWN"; }
            string output = process.StandardOutput.ReadToEnd().Trim();
            return process.ExitCode == 0 && (output == "RUNNING" || output == "STOPPED" || output == "UNKNOWN") ? output : "UNKNOWN";
        }
    }

    internal static Process StartHidden(string interpreter, string script, string workingDirectory, string outputLog)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(outputLog));
        string command = "/d /s /c \"\"" + interpreter + "\" -X utf8 -u \"" + script + "\" >> \"" + outputLog + "\" 2>&1\"";
        var info = new ProcessStartInfo(Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe", command);
        info.WorkingDirectory = workingDirectory;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.WindowStyle = ProcessWindowStyle.Hidden;
        Process process = Process.Start(info);
        if (process == null) throw new InvalidOperationException("无法启动机器人。");
        return process;
    }

    private void OpenLog()
    {
        try
        {
            if (!File.Exists(logPath)) { MessageBox.Show("还没有后台启动日志。", "运行日志", MessageBoxButtons.OK, MessageBoxIcon.Information); return; }
            Process.Start(new ProcessStartInfo("notepad.exe", "\"" + logPath + "\"") { UseShellExecute = true });
        }
        catch (Exception ex) { MessageBox.Show("无法打开日志：" + ex.Message, "运行日志", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private void SetState(string result)
    {
        if (IsDisposed) return;
        if (result == "RUNNING") { state.Text = "状态：已检测到机器人进程"; state.ForeColor = Color.FromArgb(21, 128, 82); }
        else if (result == "STOPPED") { state.Text = "状态：机器人未运行"; state.ForeColor = Color.FromArgb(92, 102, 115); }
        else if (result == "MISSING") { state.Text = "状态：找不到机器人项目或虚拟环境"; state.ForeColor = Color.Firebrick; }
        else { state.Text = "状态：无法确认，请检查权限和运行环境"; state.ForeColor = Color.Firebrick; }
        start.Enabled = result == "STOPPED";
        stop.Enabled = result == "RUNNING";
        refresh.Enabled = true;
    }

    private async Task UpdateStatus()
    {
        if (busy || IsDisposed) return;
        busy = true; refresh.Enabled = false;
        try { SetState(await Task.Run(() => Helper("status"))); }
        catch { SetState("UNKNOWN"); }
        finally { busy = false; }
    }

    private async Task StartBot()
    {
        if (busy) return;
        busy = true; start.Enabled = false; stop.Enabled = false; refresh.Enabled = false;
        try
        {
            string before = await Task.Run(() => Helper("status"));
            if (before != "STOPPED") { SetState(before); return; }
            using (Process process = StartHidden(python, bot, root, logPath)) { }
            state.Text = "正在后台启动…";
            await Task.Delay(1600);
            string after = await Task.Run(() => Helper("status"));
            SetState(after);
            if (after == "STOPPED") MessageBox.Show("机器人未保持运行，请点击“查看运行日志”检查错误。", "启动未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        catch (Exception ex) { SetState("UNKNOWN"); MessageBox.Show("启动失败：" + ex.Message, "微信机器人", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
        finally { busy = false; }
    }

    private async Task StopBot()
    {
        if (busy) return;
        busy = true; start.Enabled = false; stop.Enabled = false; refresh.Enabled = false;
        state.Text = "正在关闭机器人…";
        try
        {
            string result = await Task.Run(() => Helper("stop"));
            SetState(result);
            if (result != "STOPPED") MessageBox.Show("未能确认机器人已关闭，请检查权限。", "关闭未确认", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        catch (Exception ex) { SetState("UNKNOWN"); MessageBox.Show("关闭失败：" + ex.Message, "微信机器人", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
        finally { busy = false; }
    }
}
