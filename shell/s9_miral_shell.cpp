// S9_PANEL_ROLE_V1 (base: V36fs)
// S9_FULLSCREEN_PANEL_V1 (base: V35)
#include <exception>
#include <unordered_set>
#include <fstream>
#include <miral/application.h>
#include <vector>

// S9_CHROME_DOCKLIKE_V28
#include <miral/application_info.h>
#include <miral/window_info.h>
#include <miral/window_manager_tools.h>
#include <miral/window_specification.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <unistd.h>
#include <pwd.h>
#include <cerrno>
#include <cstring>
#include <sstream>
#include <thread>

#include <mir/scene/surface.h>
#include <cstdlib>
#include <miral/minimal_window_manager.h>
#include <miral/window_management_options.h>
#include <miral/window_specification.h>
#include <miral/window_info.h>
#include <miral/application_info.h>

#include <miral/runner.h>
#include <miral/display_configuration_option.h>
#include <miral/external_client.h>
#include <miral/cursor_theme.h>
#include <miral/wayland_extensions.h>
#include <miral/x11_support.h>
#include <miral/keymap.h>
#include <cstdio>
#include <fstream>
#include <vector>
#define S9V34_KBDREAD 1
#include <mir/input/mir_keyboard_config.h>
#include <mir/input/keymap.h>
#include <mir/input/input_device_hub.h>
#include <mir/input/device.h>
#include <mir/input/mir_pointer_config.h>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <map>
#include <memory>
#include <thread>
#include <cctype>
#include <string>
#include <mir/input/mir_touchpad_config.h>
#define S9V33_TPD 1

#include <mir/server.h>
#include <mir/graphics/display_configuration.h>
#include <mir/graphics/display_configuration_policy.h>
#include <mir/shell/display_configuration_controller.h>

#include <algorithm>
#include <cstdint>
#include <memory>
#include <utility>
#include <cctype>
#include <string>
#include <thread>
#include <fstream>
#include <iostream>
#include <cerrno>
#include <cstring>

#include <sys/stat.h>
#include <unistd.h>

// S9_ALTTAB_V1: tipos/funcoes de evento de teclado
#if __has_include(<mir_toolkit/event.h>)
#include <mir_toolkit/event.h>
#else
#include <mir_toolkit/events/input/input_event.h>
#include <mir_toolkit/events/input/keyboard_event.h>
#endif

// S9_CONFIG_V1: the desktop user and keyboard layout come from /etc/s9-ubports.conf (or the
// environment); nothing is hard-coded. Keys: S9_USER, S9_KEYMAP, S9_KEYMAP_VARIANT.
#include <fstream>
#include <pwd.h>
namespace s9cfg
{
inline std::string trim(std::string v)
{
    auto const b = v.find_first_not_of(" \t\r\n\"'");
    if (b == std::string::npos)
        return {};
    auto const e = v.find_last_not_of(" \t\r\n\"'");
    return v.substr(b, e - b + 1);
}

inline std::string get(std::string const& key)
{
    if (char const* e = std::getenv(key.c_str()))
        if (*e)
            return trim(e);

    std::ifstream f("/etc/s9-ubports.conf");
    std::string line;
    while (std::getline(f, line))
    {
        auto const p = line.find_first_not_of(" \t");
        if (p == std::string::npos || line[p] == '#')
            continue;
        line = line.substr(p);
        if (line.compare(0, key.size() + 1, key + "=") != 0)
            continue;
        auto v = line.substr(key.size() + 1);
        auto const h = v.find('#');
        if (h != std::string::npos)
            v = v.substr(0, h);
        return trim(v);
    }
    return {};
}

// Usuario da sessao: S9_USER, senao o dono do uid 1000.
inline std::string user()
{
    auto u = get("S9_USER");
    if (!u.empty())
        return u;
    if (auto const* pw = ::getpwuid(1000))
        return pw->pw_name;
    return "user";
}

inline std::string layout()
{
    auto k = get("S9_KEYMAP");
    return k.empty() ? std::string{"br"} : k;
}

inline std::string keymap_full()
{
    auto v = get("S9_KEYMAP_VARIANT");
    return v.empty() ? layout() : layout() + "+" + v;
}

// Layout "temporario" usado para forcar a reaplicacao do teclado.
inline std::string poke_alt()
{
    return layout() == "us" ? std::string{"de"} : std::string{"us"};
}
} // namespace s9cfg

namespace mg = mir::graphics;
namespace geom = mir::geometry;

namespace
{
class S9DisplayPolicy : public mg::DisplayConfigurationPolicy
{
public:
    explicit S9DisplayPolicy(
        std::shared_ptr<mg::DisplayConfigurationPolicy> wrapped)
        : wrapped{std::move(wrapped)}
    {
    }

    void apply_to(mg::DisplayConfiguration& conf) override
    {
        wrapped->apply_to(conf);

        bool dp_connected = false;

        conf.for_each_output(
            [&](mg::UserDisplayConfigurationOutput& output)
            {
                if (output.connected &&
                    !output.modes.empty() &&
                    output.type ==
                        mg::DisplayConfigurationOutputType::displayport)
                {
                    dp_connected = true;
                }
            });

        bool selected = false;

        conf.for_each_output(
            [&](mg::UserDisplayConfigurationOutput& output)
            {
                if (!output.connected || output.modes.empty())
                {
                    output.used = false;
                    return;
                }

                bool const dp =
                    output.type ==
                        mg::DisplayConfigurationOutputType::displayport;

                if (dp_connected)
                {
                    if (!dp || selected)
                    {
                        output.used = false;
                        output.power_mode = mir_power_mode_off;
                        return;
                    }

                    selected = true;

                    output.used = true;
                    output.power_mode = mir_power_mode_on;
                    output.top_left = geom::Point{0, 0};
                    output.orientation = mir_orientation_normal;
                    output.scale = 1.0f;

                    for (std::size_t i = 0;
                         i < output.modes.size();
                         ++i)
                    {
                        auto const& mode = output.modes[i];

                        if (mode.size.width.as_int() == 3840 &&
                            mode.size.height.as_int() == 2160)
                        {
                            output.current_mode_index =
                                static_cast<std::uint32_t>(i);

                            output.custom_logical_size =
                                geom::Size{3840, 1080};

                            break;
                        }
                    }

                    return;
                }

                if (dp || selected)
                {
                    output.used = false;

                    if (dp)
                        output.power_mode = mir_power_mode_off;

                    return;
                }

                selected = true;

                output.used = true;
                output.power_mode = mir_power_mode_on;
                output.top_left = geom::Point{0, 0};
                output.scale = 1.0f;
            });
    }

private:
    std::shared_ptr<mg::DisplayConfigurationPolicy> const wrapped;
};


void s9_display_policy(mir::Server& server)
{
    server.wrap_display_configuration_policy(
        [](std::shared_ptr<mg::DisplayConfigurationPolicy> const& wrapped)
            -> std::shared_ptr<mg::DisplayConfigurationPolicy>
        {
            return std::make_shared<S9DisplayPolicy>(wrapped);
        });
}


std::string lower(std::string value)
{
    std::transform(
        value.begin(),
        value.end(),
        value.begin(),
        [](unsigned char c)
        {
            return static_cast<char>(std::tolower(c));
        });

    return value;
}

bool contains(std::string const& text, char const* needle)
{
    return text.find(needle) != std::string::npos;
}

enum class S9WindowRole
{
    normal,
    desktop,
    panel
};

S9WindowRole classify(std::string const& identity)
{
    auto const id = lower(identity);

    if (contains(id, "xfdesktop"))
        return S9WindowRole::desktop;

    if (contains(id, "xfce4-panel"))
        return S9WindowRole::panel;

    return S9WindowRole::normal;
}

S9WindowRole classify(
    miral::ApplicationInfo const& app,
    miral::WindowSpecification const& spec)
{
    if (spec.application_id().is_set())
        return classify(spec.application_id().value());

    return classify(app.name());
}

S9WindowRole classify(miral::WindowInfo const& info)
{
    return classify(info.application_id());
}


// S9_CHROME_DOCKLIKE_V28
//
// Native Wayland Chrome control socket.
// All accesses to the MirAL window model are serialized
// using WindowManagerTools::invoke_under_lock().
//
// The server does not expose a public Wayland protocol.

static void s9_v28_chrome_control_server(
    miral::WindowManagerTools tools)
{
    char const* path =
        "/run/s9-miral/s9-chrome-control.sock";

    auto const user = ::getpwnam(s9cfg::user().c_str());

    if (!user)
    {
        std::cerr << "S9_V28_ERROR=no_user" << std::endl;
        return;
    }

    auto const uid = user->pw_uid;
    auto const gid = user->pw_gid;

    int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);

    if (fd < 0)
    {
        std::cerr << "S9_V28_ERROR=socket" << std::endl;
        return;
    }

    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;

    if (std::strlen(path) >= sizeof(addr.sun_path))
    {
        ::close(fd);
        return;
    }

    std::strcpy(addr.sun_path, path);

    // The runtime directory already exists in the S9
    // MirAL session. Never delete arbitrary files.
    struct stat old_path{};

    if (::lstat(path, &old_path) == 0)
    {
        if (!S_ISSOCK(old_path.st_mode))
        {
            std::cerr
                << "S9_V28_ERROR=foreign_socket_path"
                << std::endl;
            ::close(fd);
            return;
        }

        ::unlink(path);
    }

    if (::bind(fd,
               reinterpret_cast<sockaddr*>(&addr),
               sizeof(addr)) != 0)
    {
        std::cerr
            << "S9_V28_ERROR=bind errno="
            << errno << std::endl;
        ::close(fd);
        return;
    }

    if (::chown(path, uid, gid) != 0 ||
        ::chmod(path, 0600) != 0 ||
        ::listen(fd, 8) != 0)
    {
        std::cerr
            << "S9_V28_ERROR=socket_permissions_or_listen"
            << std::endl;
        ::unlink(path);
        ::close(fd);
        return;
    }

    std::cerr
        << "S9_CHROME_IPC_READY=1"
        << " socket=" << path
        << std::endl;

    MirWindowState last_normal_state =
        mir_window_state_restored;

    for (;;)
    {
        int client = ::accept(fd, nullptr, nullptr);

        if (client < 0)
            continue;

        char buffer[128]{};

        auto const n = ::recv(
            client,
            buffer,
            sizeof(buffer) - 1,
            0);

        if (n <= 0)
        {
            ::close(client);
            continue;
        }

        std::string command(buffer, n);

        auto const end = command.find_first_of(
            "\r\n \t");

        if (end != std::string::npos)
            command.resize(end);

        std::string response = "ERROR=UNKNOWN\n";

        try
        {
            tools.invoke_under_lock([&]()
            {
                // S9_CHROME_DOCKLIKE_V29
                std::vector<miral::Window> all_windows;
                std::vector<miral::Window> normal_windows;
                miral::Window chrome{};

                int count = 0;

                tools.for_each_application(
                    [&](miral::ApplicationInfo& app)
                    {
                        for (auto const& window : app.windows())
                        {
                            auto const& wi = tools.info_for(window);

                            if (wi.application_id() != "google-chrome")
                                continue;

                            ++count;
                            all_windows.push_back(window);

                            // S9_CHROME_V30_FREESTYLE
                            // Chrome Ozone/Wayland: a janela principal
                            // usa mir_window_type_freestyle (4).
                            // Aceitar normal (0) e freestyle (4).
                            // S9_CHROME_V31_PROXY_FILTER
                            //
                            // O proxy X11 e uma superficie do Xwayland.
                            // Seu WM_CLASS pode produzir o mesmo app_id
                            // da janela Chrome Wayland verdadeira.
                            //
                            // Excluir somente superficies de sessoes
                            // cujo processo proprietario e Xwayland.

                            auto const owner = window.application();

                            auto const owner_pid =
                                owner ? miral::pid_of(owner) : -1;

                            std::string owner_comm;

                            if (owner_pid > 0)
                            {
                                std::ifstream proc(
                                    "/proc/" +
                                    std::to_string(owner_pid) +
                                    "/comm");

                                std::getline(proc, owner_comm);
                            }

                            if (owner_comm == "Xwayland")
                                continue;

                            // S9_CHROME_V32_BRIDGE_PROXY_FILTER
                            //
                            // No S9, o cliente X11 proxy aparece
                            // como sessao do processo Python que
                            // criou a janela, nao como Xwayland.
                            //
                            // Excluir apenas o proxy criado pelo
                            // nosso servico Docklike.

                            if (owner_comm == "python3" &&
                                owner_pid > 0)
                            {
                                std::ifstream command_file(
                                    "/proc/" +
                                    std::to_string(owner_pid) +
                                    "/cmdline",
                                    std::ios::binary);

                                std::string argument;
                                bool is_bridge = false;

                                while (std::getline(
                                    command_file,
                                    argument,
                                    '\0'))
                                {
                                    if (argument ==
                                        "/usr/local/libexec/"
                                        "s9-docklike-ewmh.py")
                                    {
                                        is_bridge = true;
                                        break;
                                    }
                                }

                                if (is_bridge)
                                    continue;
                            }

                            if (wi.type() == mir_window_type_normal ||
                                wi.type() == mir_window_type_freestyle)
                                normal_windows.push_back(window);
                        }
                    });

                if (command == "LIST")
                {
                    std::ostringstream out;

                    out << "SURFACES=" << count << "\n"
                        << "NORMAL_WINDOWS="
                        << normal_windows.size() << "\n";

                    int index = 0;

                    for (auto const& window : all_windows)
                    {
                        auto const& wi = tools.info_for(window);

                        std::string name = wi.name();

                        for (auto& c : name)
                            if (c == '\n' || c == '\r')
                                c = ' ';

                        // S9_CHROME_V31_LIST_OWNER
                        auto const owner = window.application();

                        auto const owner_pid =
                            owner ? miral::pid_of(owner) : -1;

                        std::string owner_comm;

                        if (owner_pid > 0)
                        {
                            std::ifstream proc(
                                "/proc/" +
                                std::to_string(owner_pid) +
                                "/comm");

                            std::getline(proc, owner_comm);
                        }

                        out << "WINDOW_" << index
                            << "_PID=" << owner_pid
                            << "\nWINDOW_" << index
                            << "_OWNER_COMM=" << owner_comm
                            << "\nWINDOW_" << index
                            << "_IS_XWAYLAND="
                            << (owner_comm == "Xwayland")
                            << "\n";

                        out << "WINDOW_" << index
                            << "_TYPE="
                            << static_cast<int>(wi.type())
                            << "\nWINDOW_" << index
                            << "_STATE="
                            << static_cast<int>(wi.state())
                            << "\nWINDOW_" << index
                            << "_FOCUSED="
                            << (tools.active_window() == window)
                            << "\nWINDOW_" << index
                            << "_NAME=" << name << "\n";

                        ++index;
                    }

                    response = out.str();
                    return;
                }

                if (!normal_windows.empty())
                {
                    chrome = normal_windows.front();

                    for (auto const& window : normal_windows)
                    {
                        if (tools.active_window() == window)
                        {
                            chrome = window;
                            break;
                        }
                    }
                }

                if (!chrome)
                {
                    response =
                        "PRESENT=0\nWINDOWS=0\n";
                    return;
                }

                auto const& info =
                    tools.info_for(chrome);

                auto const state = info.state();

                if (state != mir_window_state_minimized)
                    last_normal_state = state;

                auto const focused =
                    tools.active_window() == chrome;

                std::string title = info.name();

                for (auto& c : title)
                {
                    if (c == '\n' || c == '\r')
                        c = ' ';
                }

                if (command == "STATUS")
                {
                    std::ostringstream out;

                    out << "PRESENT=1\n"
                        << "WINDOWS=" << normal_windows.size() << "\n"
                        << "SURFACES=" << count << "\n"
                        << "STATE="
                        << static_cast<int>(state)
                        << "\n"
                        << "MINIMIZED="
                        << (state ==
                            mir_window_state_minimized)
                        << "\n"
                        << "FOCUSED=" << focused << "\n"
                        << "TITLE=" << title << "\n";

                    response = out.str();
                    return;
                }

                if (command == "MINIMIZE")
                {
                    if (state != mir_window_state_minimized)
                    {
                        miral::WindowSpecification spec;
                        spec.state() =
                            mir_window_state_minimized;

                        tools.modify_window(chrome, spec);
                    }

                    response = "OK=MINIMIZE\n";
                }
                else if (command == "RESTORE" ||
                         command == "ACTIVATE")
                {
                    if (state == mir_window_state_minimized)
                    {
                        miral::WindowSpecification spec;
                        spec.state() = last_normal_state;

                        tools.modify_window(chrome, spec);
                    }

                    tools.select_active_window(chrome);
                    response = "OK=ACTIVATE\n";
                }
                else if (command == "CLOSE")
                {
                    // S9_CHROME_DOCKLIKE_V29_CLOSE
                    // Fechamento normal de todas as janelas
                    // principais. Nao fechar menus e popups.

                    int requested = 0;

                    for (auto const& window : normal_windows)
                    {
                        auto const& wi = tools.info_for(window);

                        std::cerr
                            << "S9_V29_CLOSE_WINDOW"
                            << " name=" << wi.name()
                            << " type="
                            << static_cast<int>(wi.type())
                            << " state="
                            << static_cast<int>(wi.state())
                            << std::endl;

                        tools.ask_client_to_close(window);
                        ++requested;
                    }

                    std::cerr
                        << "S9_V29_CLOSE_REQUESTS="
                        << requested
                        << std::endl;

                    response = "OK=CLOSE_REQUEST\n";
                }
                else
                {
                    response = "ERROR=UNKNOWN_COMMAND\n";
                }
            });
        }
        catch (std::exception const& e)
        {
            response =
                std::string{"ERROR=MIRAL "} +
                e.what() + "\n";
        }
        catch (...)
        {
            response = "ERROR=UNEXPECTED\n";
        }

        // Client may disconnect during a window transition.
        ::send(
            client,
            response.data(),
            response.size(),
            MSG_NOSIGNAL);

        ::close(client);
    }
}

class S9WindowManager : public miral::MinimalWindowManager
{
    /*
     * S9_MAXIMIZE_PANEL_V25
     *
     * Keep a handle to the actual XFCE dock surface.
     * Its geometry is queried when maximizing.
     *
     * Do not use a fixed screen resolution or panel height.
     */
    miral::Window xfce_panel_window;

    /*
     * S9_FULLSCREEN_PANEL_V1
     *
     * Janela normal (ou dialogo cujo pai esta) em tela cheia e ativa:
     * o painel desce da camada "above" para "application" e a janela
     * e levantada; ao sair, o painel volta para "above".
     */
    bool s9fs_lowered{false};
    miral::Window s9fs_window;

    MirDepthLayer s9fs_panel_layer() const
    {
        return s9fs_lowered ?
            mir_depth_layer_application :
            mir_depth_layer_above;
    }

public:

    // ---- S9_READY_GUARD_V1 ----
    /*
     * O MirAL (basic_window_manager.cpp, add_surface) registra um callback de
     * "janela pronta" que guarda uma REFERENCIA ao WindowInfo (elemento do mapa
     * window_info). Se a janela X11 e removida antes do primeiro commit do
     * wl_surface (popup/dialogo criado e destruido em milissegundos), o elemento
     * ja foi apagado e o callback usa memoria liberada: excecao std::out_of_range
     * (SIGBUS/abort) ou corrupcao de heap (SEGV em lugares aleatorios).
     * Aqui guardamos os enderecos dos WindowInfo vivos (advise_new_window /
     * advise_delete_window) e ignoramos handle_window_ready de endereco morto,
     * sem tocar no objeto. Excecoes da politica base tambem sao contidas.
     * Log: "S9_READY_GUARD stale-ignored count=N" = o defeito foi evitado.
     */
    std::unordered_set<void const*> s9rg_live;
    unsigned long s9rg_stale{0};

    void s9rg_on_new(miral::WindowInfo const& info)
    {
        s9rg_live.insert(static_cast<void const*>(&info));
    }

    void s9rg_on_delete(miral::WindowInfo const& info)
    {
        s9rg_live.erase(static_cast<void const*>(&info));
    }

    void handle_window_ready(miral::WindowInfo& window_info) override
    {
        if (s9rg_live.find(static_cast<void const*>(&window_info)) == s9rg_live.end())
        {
            ++s9rg_stale;
            if (s9rg_stale <= 50 || s9rg_stale % 50 == 0)
                std::cerr << "S9_READY_GUARD stale-ignored count=" << s9rg_stale << std::endl;
            return;
        }

        try
        {
            miral::MinimalWindowManager::handle_window_ready(window_info);
        }
        catch (std::exception const& e)
        {
            std::cerr << "S9_READY_GUARD excecao contida: " << e.what() << std::endl;
        }
        catch (...)
        {
            std::cerr << "S9_READY_GUARD excecao desconhecida contida" << std::endl;
        }
    }

    void advise_new_window(
        miral::WindowInfo const& info) override
    {
        s9rg_on_new(info);

        {
            auto const p = info.window().top_left();
            auto const s = info.window().size();

            std::cerr
                << "S9_V26_STATE_NEW"
                << " app=" << info.application_id()
                << " state=" << static_cast<int>(info.state())
                << " maximized=" <<
                    (info.state() == mir_window_state_maximized)
                << " fullscreen=" <<
                    (info.state() == mir_window_state_fullscreen)
                << " x=" << p.x.as_int()
                << " y=" << p.y.as_int()
                << " w=" << s.width.as_int()
                << " h=" << s.height.as_int()
                << " panel_known=" << bool(xfce_panel_window)
                << std::endl;
        }


        auto const trace_window = info.window();

        if (trace_window)
        {
            auto const trace_size = trace_window.size();

            std::cerr
                << "S9_V26_NEW"
                << " app=" << info.application_id()
                << " role=" << static_cast<int>(s9pr_role(info))
                << " w=" << trace_size.width.as_int()
                << " h=" << trace_size.height.as_int()
                << std::endl;
        }

        if (s9pr_role(info) != S9WindowRole::panel)
            return;

        auto const window = info.window();
        auto const size = window.size();

        /*
         * The main panel spans most of the display.
         * Exclude Clock/calendar and panel popups.
         */
        auto const output = tools.active_output();

        if (size.width.as_int() >=
                output.size.width.as_int() * 3 / 4 &&
            size.height.as_int() >= 16 &&
            size.height.as_int() <= 160)
        {
            xfce_panel_window = window;
        }
    }

    void advise_delete_window(
        miral::WindowInfo const& info) override
    {
        s9rg_on_delete(info);
        s9fs_on_delete(info);
        if (xfce_panel_window &&
            info.window() == xfce_panel_window)
        {
            xfce_panel_window = {};
            s9fs_panel_gone();
        }
    }

    // ---- S9_PANEL_ROLE_V1 ----
    /*
     * Papel "painel" so para a barra do XFCE e seus popups/menus
     * (janelas finas ou filhas da barra). Janelas grandes do processo
     * xfce4-panel sem pai (Panel Preferences) sao janelas normais:
     * ficam na camada de aplicacao, recebem a moldura do Mir e podem
     * ser movidas/redimensionadas.
     */
    S9WindowRole s9pr_role(
        miral::WindowInfo const& info,
        int const depth = 0)
    {
        auto const base = classify(info);

        /* S9_DESKTOP_MENU_V1: janela filha (transient) do xfdesktop = menu de
         * contexto da area de trabalho. E janela normal; so a janela Desktop
         * (sem pai) continua no papel desktop/fundo. */
        if (base == S9WindowRole::desktop && info.parent())
            return S9WindowRole::normal;

        if (base != S9WindowRole::panel)
            return base;

        auto const window = info.window();

        if (xfce_panel_window && window == xfce_panel_window)
            return S9WindowRole::panel;

        if (depth < 4)
        {
            auto const parent = info.parent();

            if (parent)
                return s9pr_role(tools.info_for(parent), depth + 1);
        }

        auto const size = window.size();

        if (size.width.as_int() > 160 && size.height.as_int() > 160)
            return S9WindowRole::normal;

        return S9WindowRole::panel;
    }

    S9WindowRole s9pr_place_role(
        miral::ApplicationInfo const& app,
        miral::WindowSpecification const& spec)
    {
        auto const base = classify(app, spec);

        /* S9_DESKTOP_MENU_V1: filha do xfdesktop (menu) nao e fundo. */
        if (base == S9WindowRole::desktop && spec.parent().is_set())
            return S9WindowRole::normal;

        if (base != S9WindowRole::panel)
            return base;

        /* filhas (menus/popups da barra): mantem; o papel final vem
         * depois, por s9pr_role(info), que resolve o pai. */
        if (spec.parent().is_set())
            return base;

        if (spec.size().is_set())
        {
            auto const& size = spec.size().value();

            if (size.width.as_int() > 160 && size.height.as_int() > 160)
            {
                std::cerr
                    << "S9_PANEL_ROLE normal-by-size w="
                    << size.width.as_int()
                    << " h=" << size.height.as_int()
                    << std::endl;

                return S9WindowRole::normal;
            }
        }

        return base;
    }

    // ---- S9_DESKTOP_MENU_V1 ----
    /*
     * Janela filha (transient) de uma janela do xfdesktop = menu de contexto
     * da area de trabalho (botao direito) ou submenu. Antes, todo papel
     * "desktop" ia para a camada de fundo e o menu ficava ATRAS das janelas
     * de aplicativo. Agora a filha fica na camada "above" (como os menus do
     * painel); so a janela Desktop (sem pai) continua no fundo.
     */
    bool s9dm_is_desktop_child(
        miral::ApplicationInfo const& app,
        miral::WindowSpecification const& spec)
    {
        return classify(app, spec) == S9WindowRole::desktop &&
               spec.parent().is_set();
    }

    // ---- S9_FULLSCREEN_PANEL_V1 ----
    bool s9fs_find_fullscreen(
        miral::WindowInfo const& info,
        MirWindowState const info_state,
        miral::Window& target)
    {
        miral::Window w = info.window();
        MirWindowState st = info_state;

        for (int depth = 0; depth < 4 && w; ++depth)
        {
            auto const& wi = tools.info_for(w);

            if (s9pr_role(wi) != S9WindowRole::normal)
                return false;

            if (depth > 0)
                st = wi.state();

            if (st == mir_window_state_fullscreen)
            {
                target = w;
                return true;
            }

            w = wi.parent();
        }

        return false;
    }

    void s9fs_set(bool lowered, miral::Window const& target)
    {
        if (!xfce_panel_window)
        {
            s9fs_lowered = false;
            s9fs_window = miral::Window{};
            return;
        }

        if (lowered == s9fs_lowered &&
            (!lowered || target == s9fs_window))
            return;

        s9fs_lowered = lowered;
        s9fs_window = lowered ? target : miral::Window{};

        miral::WindowSpecification spec;
        spec.depth_layer() = s9fs_panel_layer();
        tools.modify_window(xfce_panel_window, spec);

        if (lowered && target)
            tools.raise_tree(target);

        std::cerr
            << "S9_FS_PANEL lowered=" << lowered
            << std::endl;
    }

    void s9fs_panel_gone()
    {
        s9fs_lowered = false;
        s9fs_window = miral::Window{};
    }

    void s9fs_on_delete(miral::WindowInfo const& info)
    {
        if (s9fs_lowered && info.window() == s9fs_window)
            s9fs_set(false, miral::Window{});
    }

    void advise_focus_gained(
        miral::WindowInfo const& info) override
    {
        miral::MinimalWindowManager::advise_focus_gained(info);
        s9al_on_focus(info); // S9_ALTTAB_V1

        miral::Window target;
        bool const fs =
            s9fs_find_fullscreen(info, info.state(), target);
        s9fs_set(fs, target);
    }

    void advise_state_change(
        miral::WindowInfo const& info,
        MirWindowState state) override
    {
        miral::MinimalWindowManager::advise_state_change(info, state);

        if (!(tools.active_window() == info.window()))
            return;

        miral::Window target;
        bool const fs =
            s9fs_find_fullscreen(info, state, target);
        s9fs_set(fs, target);
    }

    auto s9_v25_confirm_placement(
        miral::WindowInfo const& info,
        MirWindowState new_state,
        geom::Rectangle const& requested)
        -> geom::Rectangle
    {
        /*
         * Only maximized/vertical-maximized windows.
         * Fullscreen and restored windows are untouched.
         */
        if (new_state != mir_window_state_maximized &&
            new_state != mir_window_state_vertmaximized)
        {
            return requested;
        }

        if (s9pr_role(info) != S9WindowRole::normal ||
            !xfce_panel_window)
        {
            return requested;
        }

        auto const panel_position =
            xfce_panel_window.top_left();

        auto const panel_size =
            xfce_panel_window.size();

        auto const panel_x = panel_position.x.as_int();
        auto const panel_y = panel_position.y.as_int();
        auto const panel_w = panel_size.width.as_int();
        auto const panel_h = panel_size.height.as_int();

        auto const x = requested.top_left.x.as_int();
        auto const y = requested.top_left.y.as_int();
        auto const w = requested.size.width.as_int();
        auto const h = requested.size.height.as_int();

        if (w < 200 || h < 200 ||
            panel_h < 16 || panel_h > 160 ||
            panel_w < w * 3 / 4)
        {
            return requested;
        }

        /*
         * Require the panel to span this output.
         * Do not apply a panel on another monitor.
         */
        if (panel_x > x + 32 ||
            panel_x + panel_w < x + w - 32)
        {
            return requested;
        }

        auto const panel_bottom = panel_y + panel_h;
        auto const display_bottom = y + h;

        /*
         * XWayland clients can have a negative content
         * offset, observed as -24 px on Thunar.
         *
         * Keep the actual client window below the dock,
         * not merely the Mir frame.
         */
        int title_offset = 0;

        std::shared_ptr<mir::scene::Surface> surface =
            info.window();

        if (surface)
        {
            auto const offset =
                surface->content_offset().dy.as_int();

            if (offset < 0 && offset >= -96)
                title_offset = -offset;
        }

        int new_y = y;
        int new_h = h;

        /*
         * Top dock: reserve dock and decoration offset.
         */
        if (panel_y >= y - 16 &&
            panel_y <= y + 32)
        {
            new_y = panel_bottom + title_offset;
            new_h = display_bottom - new_y;
        }
        /*
         * Bottom dock: reserve its current geometry.
         */
        else if (panel_bottom >= display_bottom - 32 &&
                 panel_bottom <= display_bottom + 16)
        {
            new_h = panel_y - y;
        }
        else
        {
            return requested;
        }

        if (new_h < 150 ||
            new_y < y ||
            new_y + new_h > display_bottom)
        {
            return requested;
        }

        return geom::Rectangle{
            geom::Point{x, new_y},
            geom::Size{w, new_h}
        };
    }


    /*
     * S9_MAXIMIZE_PANEL_V26_TRACE
     *
     * Preserve the complete V25 placement algorithm.
     * Trace native Wayland and XWayland placement.
     */
    auto confirm_placement_on_display(
        miral::WindowInfo const& info,
        MirWindowState new_state,
        geom::Rectangle const& requested)
        -> geom::Rectangle override
    {
        auto const corrected =
            s9_v25_confirm_placement(
                info, new_state, requested);

        int content_dy = 0;

        std::shared_ptr<mir::scene::Surface> surface =
            info.window();

        if (surface)
            content_dy =
                surface->content_offset().dy.as_int();

        std::cerr
            << "S9_V26_CONFIRM"
            << " app=" << info.application_id()
            << " role=" << static_cast<int>(s9pr_role(info))
            << " state=" << static_cast<int>(new_state)
            << " panel=" << (xfce_panel_window ? 1 : 0)
            << " content_dy=" << content_dy

            << " requested="
            << requested.top_left.x.as_int() << ","
            << requested.top_left.y.as_int() << ","
            << requested.size.width.as_int() << ","
            << requested.size.height.as_int()

            << " result="
            << corrected.top_left.x.as_int() << ","
            << corrected.top_left.y.as_int() << ","
            << corrected.size.width.as_int() << ","
            << corrected.size.height.as_int()

            << std::endl;

        return corrected;
    }


    /*
     * S9_MAXIMIZE_CHROME_V27
     *
     * Chrome native Wayland creates an already maximized
     * surface covering the complete output.
     *
     * V25's confirm_placement_on_display callback is not
     * invoked for that initial placement.
     *
     * Preserve V25 and constrain only Chrome maximized
     * windows through the creation/modification callbacks.
     */

    bool s9_v27_chrome_workarea(
        geom::Point const& window_position,
        geom::Size const& window_size,
        geom::Rectangle& usable)
    {
        if (!xfce_panel_window)
            return false;

        auto const output = tools.active_output();

        auto const output_w = output.size.width.as_int();
        auto const output_h = output.size.height.as_int();

        auto const panel_pos = xfce_panel_window.top_left();
        auto const panel_size = xfce_panel_window.size();

        int const px = panel_pos.x.as_int();
        int const py = panel_pos.y.as_int();
        int const pw = panel_size.width.as_int();
        int const ph = panel_size.height.as_int();

        int const wx = window_position.x.as_int();
        int const wy = window_position.y.as_int();
        int const ww = window_size.width.as_int();
        int const wh = window_size.height.as_int();

        if (output_w < 300 || output_h < 300 ||
            ph < 16 || ph > 160 ||
            pw < output_w * 3 / 4 ||
            pw > output_w + 64 ||
            ww < output_w * 3 / 4)
        {
            return false;
        }

        /*
         * Only act when the Chrome window and the XFCE
         * panel span the same horizontal output region.
         */
        if (wx < px - 32 || wx > px + 32 ||
            wx + ww < px + pw - 32)
        {
            return false;
        }

        int const panel_bottom = py + ph;

        /*
         * Top panel.
         */
        if (wy >= py - 32 &&
            wy <= panel_bottom + 32)
        {
            usable = geom::Rectangle{
                geom::Point{px, panel_bottom},
                geom::Size{output_w, output_h - ph}
            };

            return true;
        }

        /*
         * Bottom panel.
         */
        if (std::abs((wy + wh) - panel_bottom) <= ph + 32)
        {
            usable = geom::Rectangle{
                geom::Point{px, panel_bottom - output_h},
                geom::Size{output_w, output_h - ph}
            };

            return true;
        }

        return false;
    }

    auto place_new_window(
        miral::ApplicationInfo const& app,
        miral::WindowSpecification const& requested)
        -> miral::WindowSpecification override
    {
        /*
         * Execute the complete original S9 policy first.
         */
        auto result =
            s9_v26_original_place_new_window(
                app, requested);

        auto const& title = requested.name();
        auto const& state = requested.state();

        if (!title.is_set() ||
            title.value().find("Google Chrome") ==
                std::string::npos ||
            !state.is_set() ||
            state.value() != mir_window_state_maximized ||
            !result.top_left().is_set() ||
            !result.size().is_set())
        {
            return result;
        }

        geom::Rectangle usable{};

        auto const original_pos = result.top_left().value();
        auto const original_size = result.size().value();

        if (!s9_v27_chrome_workarea(
                original_pos,
                original_size,
                usable))
        {
            return result;
        }

        result.top_left() = usable.top_left;
        result.size() = usable.size;

        std::cerr
            << "S9_V27_CHROME_PLACE"
            << " original="
            << original_pos.x.as_int() << ","
            << original_pos.y.as_int() << ","
            << original_size.width.as_int() << ","
            << original_size.height.as_int()
            << " corrected="
            << usable.top_left.x.as_int() << ","
            << usable.top_left.y.as_int() << ","
            << usable.size.width.as_int() << ","
            << usable.size.height.as_int()
            << std::endl;

        return result;
    }

    void handle_modify_window(
        miral::WindowInfo& info,
        miral::WindowSpecification const& requested) override
    {
        if (info.application_id() != "google-chrome" ||
            info.state() != mir_window_state_maximized)
        {
            s9_v26_original_handle_modify_window(
                info, requested);
            return;
        }

        geom::Rectangle usable{};

        auto const position = info.window().top_left();
        auto const size = info.window().size();

        if (!s9_v27_chrome_workarea(
                position, size, usable))
        {
            s9_v26_original_handle_modify_window(
                info, requested);
            return;
        }

        /*
         * Do not overwrite a request explicitly leaving
         * the maximized state, especially fullscreen.
         */
        if (requested.state().is_set() &&
            requested.state().value() !=
                mir_window_state_maximized)
        {
            s9_v26_original_handle_modify_window(
                info, requested);
            return;
        }

        /*
         * Preserve all other client properties.
         * Only correct the managed position and size.
         */
        miral::WindowSpecification corrected = requested;

        corrected.top_left() = usable.top_left;
        corrected.size() = usable.size;

        std::cerr
            << "S9_V27_CHROME_MODIFY"
            << " previous="
            << position.x.as_int() << ","
            << position.y.as_int() << ","
            << size.width.as_int() << ","
            << size.height.as_int()
            << " corrected="
            << usable.top_left.x.as_int() << ","
            << usable.top_left.y.as_int() << ","
            << usable.size.width.as_int() << ","
            << usable.size.height.as_int()
            << std::endl;

        s9_v26_original_handle_modify_window(
            info, corrected);
    }

    // ---- S9_ALTTAB_V1 ----
    /*
     * Alt+Tab proprio. O MinimalWindowManager chama tools.focus_next_application(),
     * que cicla TUDO que e ativavel: inclusive o fundo (xfdesktop, tipo DESKTOP) e a
     * barra (xfce4-panel, tipo DOCK). Resultado: dois "Tab" extras sem efeito visivel
     * entre uma janela e outra. Aqui o ciclo so inclui janelas de papel normal
     * (s9pr_role), sem pai, ativaveis e nao ocultas, em ordem de uso recente (MRU).
     * A lista e congelada enquanto o Alt estiver pressionado; ao soltar, a janela
     * escolhida vai para o topo da MRU. Alt+Shift+Tab cicla ao contrario.
     * Qualquer outra tecla segue para o MinimalWindowManager (Alt+F4, Alt+` ...).
     * Log (60 primeiras): "S9_ALTTAB_V1 ..."
     */
    std::vector<miral::Window> s9al_mru;
    std::vector<miral::Window> s9al_list;
    int s9al_pos{-1};
    bool s9al_cycling{false};
    unsigned long s9al_logn{0};

    void s9al_touch(miral::Window const& w)
    {
        if (!w)
            return;

        for (auto it = s9al_mru.begin(); it != s9al_mru.end();)
        {
            if (*it == w)
                it = s9al_mru.erase(it);
            else
                ++it;
        }

        s9al_mru.insert(s9al_mru.begin(), w);

        if (s9al_mru.size() > 256)
            s9al_mru.erase(s9al_mru.begin() + 256, s9al_mru.end());
    }

    void s9al_on_focus(miral::WindowInfo const& info)
    {
        if (!s9al_cycling)
            s9al_touch(info.window());
    }

    miral::Window s9al_root(miral::Window w)
    {
        for (int i = 0; w && i < 8; ++i)
        {
            try
            {
                auto const p = tools.info_for(w).parent();

                if (!p)
                    break;

                w = p;
            }
            catch (...)
            {
                break;
            }
        }

        return w;
    }

    std::vector<miral::Window> s9al_build()
    {
        std::vector<miral::Window> found;

        tools.for_each_application(
            [&](miral::ApplicationInfo& app)
            {
                for (auto const& w : app.windows())
                {
                    try
                    {
                        auto const& wi = tools.info_for(w);

                        if (wi.parent() || !wi.can_be_active())
                            continue;

                        if (s9pr_role(wi) != S9WindowRole::normal)
                            continue;

                        if (wi.state() == mir_window_state_hidden)
                            continue;

                        found.push_back(w);
                    }
                    catch (...)
                    {
                    }
                }
            });

        std::vector<miral::Window> ordered;

        for (auto const& m : s9al_mru)
        {
            for (auto const& f : found)
            {
                if (f == m)
                {
                    ordered.push_back(f);
                    break;
                }
            }
        }

        for (auto const& f : found)
        {
            bool in = false;

            for (auto const& o : ordered)
            {
                if (o == f)
                {
                    in = true;
                    break;
                }
            }

            if (!in)
                ordered.push_back(f);
        }

        return ordered;
    }

    void s9al_activate(miral::Window const& w)
    {
        try
        {
            if (tools.info_for(w).state() == mir_window_state_minimized)
            {
                miral::WindowSpecification spec;
                spec.state() = mir_window_state_restored;
                tools.modify_window(w, spec);
            }
        }
        catch (...)
        {
        }

        tools.select_active_window(w);
        tools.raise_tree(w);
    }

    void s9al_end()
    {
        s9al_cycling = false;
        s9al_list.clear();
        s9al_pos = -1;
        s9al_touch(s9al_root(tools.active_window()));
    }

    void s9al_step(bool const reverse)
    {
        if (!s9al_cycling)
        {
            s9al_list = s9al_build();
            s9al_pos = -1;

            auto const root = s9al_root(tools.active_window());

            for (size_t i = 0; i < s9al_list.size(); ++i)
            {
                if (s9al_list[i] == root)
                {
                    s9al_pos = static_cast<int>(i);
                    break;
                }
            }

            s9al_cycling = true;

            if (++s9al_logn <= 60)
            {
                std::cerr << "S9_ALTTAB_V1 inicio ciclo n=" << s9al_list.size()
                          << " pos=" << s9al_pos << " janelas:";

                for (auto const& w : s9al_list)
                {
                    try
                    {
                        auto const& wi = tools.info_for(w);
                        std::cerr << " [" << wi.application_id() << "|" << wi.name() << "]";
                    }
                    catch (...)
                    {
                    }
                }

                std::cerr << std::endl;
            }
        }

        for (size_t tries = 0; tries < 16 && !s9al_list.empty(); ++tries)
        {
            int const n = static_cast<int>(s9al_list.size());

            if (n == 1 && s9al_pos == 0)
                return;

            int next;

            if (s9al_pos < 0)
                next = reverse ? n - 1 : 0;
            else
                next = (s9al_pos + (reverse ? n - 1 : 1)) % n;

            auto const w = s9al_list[next];
            bool alive = true;

            try
            {
                tools.info_for(w);
            }
            catch (...)
            {
                alive = false;
            }

            if (!alive)
            {
                s9al_list.erase(s9al_list.begin() + next);

                if (next < s9al_pos)
                    --s9al_pos;

                continue;
            }

            s9al_pos = next;
            s9al_activate(w);
            return;
        }
    }

    bool handle_keyboard_event(MirKeyboardEvent const* event) override
    {
        auto const action = mir_keyboard_event_action(event);
        auto const scan = mir_keyboard_event_scan_code(event);
        unsigned const mods = static_cast<unsigned>(mir_keyboard_event_modifiers(event));
        unsigned const alt = static_cast<unsigned>(mir_input_event_modifier_alt);
        unsigned const shift = static_cast<unsigned>(mir_input_event_modifier_shift);
        unsigned const sh = mods & (alt | shift |
            static_cast<unsigned>(mir_input_event_modifier_sym) |
            static_cast<unsigned>(mir_input_event_modifier_ctrl) |
            static_cast<unsigned>(mir_input_event_modifier_meta));

        if (s9al_cycling)
        {
            bool const alt_up =
                action == mir_keyboard_action_up && (scan == 56 || scan == 100);

            if (alt_up || !(mods & alt))
                s9al_end();
        }

        if (action == mir_keyboard_action_down && scan == 15 &&
            (sh == alt || sh == (alt | shift)))
        {
            s9al_step(sh != alt);
            return true;
        }

        return miral::MinimalWindowManager::handle_keyboard_event(event);
    }
    explicit S9WindowManager(miral::WindowManagerTools const& tools) :
        miral::MinimalWindowManager{tools}
    {
        // S9_CHROME_DOCKLIKE_V28
        // Runs outside the window manager's policy callbacks.
        // All model operations use invoke_under_lock().
        std::thread([control_tools = tools]() mutable
        {
            s9_v28_chrome_control_server(control_tools);
        }).detach();
    }

    auto s9_v26_original_place_new_window(
        miral::ApplicationInfo const& app,
        miral::WindowSpecification const& requested)
        -> miral::WindowSpecification
    {

        {
            auto const& state = requested.state();
            auto const& size = requested.size();
            auto const& pos = requested.top_left();
            auto const& name = requested.name();

            std::cerr
                << "S9_V26_STATE_PLACE"
                << " app=" << app.name()
                << " name="
                << (name.is_set() ? name.value() : "")
                << " state_set=" << state.is_set()
                << " state="
                << (state.is_set()
                    ? static_cast<int>(state.value())
                    : -1)
                << " w="
                << (size.is_set()
                    ? size.value().width.as_int()
                    : -1)
                << " h="
                << (size.is_set()
                    ? size.value().height.as_int()
                    : -1)
                << " x="
                << (pos.is_set()
                    ? pos.value().x.as_int()
                    : -1)
                << " y="
                << (pos.is_set()
                    ? pos.value().y.as_int()
                    : -1)
                << std::endl;
        }


        std::cerr
            << "S9_V26_PLACE"
            << " app=" << app.name()
            << std::endl;

        auto specification =
            miral::MinimalWindowManager::place_new_window(
                app,
                requested);

        bool const s9dm_menu =
            s9dm_is_desktop_child(app, specification);

        switch (s9pr_place_role(app, specification))
        {
        case S9WindowRole::desktop:
            /*
             * Lowest compositor layer.
             *
             * No raise_tree() from a normal application can place an
             * application above/below this relationship incorrectly.
             */
            specification.depth_layer() =
                mir_depth_layer_background;
            break;

        case S9WindowRole::panel:
            /*
             * Above ordinary applications.
             *
             * Keep the geometry requested by xfce4-panel itself.
             */
            specification.depth_layer() =
                s9fs_panel_layer();
            break;

        case S9WindowRole::normal:
            /*
             * Preserve any explicit client request.
             *
             * XWayland windows without an explicit depth layer naturally
             * default to mir_depth_layer_application.
             */
            if (s9dm_menu)
            {
                /* S9_DESKTOP_MENU_V1 */
                specification.depth_layer() =
                    mir_depth_layer_above;
                std::cerr
                    << "S9_DESKTOP_MENU_V1 above(place) app="
                    << app.name() << std::endl;
            }
            break;
        }

        return specification;
    }

    void s9_v26_original_handle_modify_window(
        miral::WindowInfo& info,
        miral::WindowSpecification const& requested)
    {

        {
            auto const& requested_state = requested.state();
            auto const& requested_size = requested.size();
            auto const& requested_pos = requested.top_left();

            std::cerr
                << "S9_V26_STATE_MOD"
                << " app=" << info.application_id()
                << " previous_state="
                << static_cast<int>(info.state())
                << " state_set=" << requested_state.is_set()
                << " requested_state="
                << (requested_state.is_set()
                    ? static_cast<int>(requested_state.value())
                    : -1)
                << " size_set=" << requested_size.is_set()
                << " requested_w="
                << (requested_size.is_set()
                    ? requested_size.value().width.as_int()
                    : -1)
                << " requested_h="
                << (requested_size.is_set()
                    ? requested_size.value().height.as_int()
                    : -1)
                << " pos_set=" << requested_pos.is_set()
                << " requested_x="
                << (requested_pos.is_set()
                    ? requested_pos.value().x.as_int()
                    : -1)
                << " requested_y="
                << (requested_pos.is_set()
                    ? requested_pos.value().y.as_int()
                    : -1)
                << std::endl;
        }


        std::cerr
            << "S9_V26_MODIFY"
            << " app=" << info.application_id()
            << " role=" << static_cast<int>(s9pr_role(info))
            << std::endl;

        miral::WindowSpecification specification = requested;

        /*
         * Do not permit later X11 property/state changes to accidentally
         * move XFCE desktop/panel out of their compositor layers.
         */
        switch (s9pr_role(info))
        {
        case S9WindowRole::desktop:
            specification.depth_layer() =
                mir_depth_layer_background;
            break;

        case S9WindowRole::panel:
            specification.depth_layer() =
                s9fs_panel_layer();
            break;

        case S9WindowRole::normal:
            if (classify(info) == S9WindowRole::desktop)
            {
                /* S9_DESKTOP_MENU_V1: filha do xfdesktop (role normal
                 * por s9pr_role) nunca volta para o fundo. */
                specification.depth_layer() =
                    mir_depth_layer_above;

                static int s9dm_logged = 0;
                if (s9dm_logged++ < 20)
                    std::cerr
                        << "S9_DESKTOP_MENU_V1 above(modify) app="
                        << info.application_id() << std::endl;
            }
            break;
        }

        miral::MinimalWindowManager::handle_modify_window(
            info,
            specification);
    }

    void handle_request_move(
        miral::WindowInfo& info,
        MirInputEvent const* event) override
    {
        /*
         * Desktop and panel are shell components, not draggable
         * application windows.
         */
        if (s9pr_role(info) != S9WindowRole::normal)
            return;

        miral::MinimalWindowManager::handle_request_move(
            info,
            event);
    }

    void handle_request_resize(
        miral::WindowInfo& info,
        MirInputEvent const* event,
        MirResizeEdge edge) override
    {
        if (s9pr_role(info) != S9WindowRole::normal)
            return;

        miral::MinimalWindowManager::handle_request_resize(
            info,
            event,
            edge);
    }
};


/*
 * TASK12N runtime orientation control
 *
 * /run/s9-displayctl accepts:
 *
 *   portrait
 *   landscape-right
 *   landscape-left
 *   inverted
 *
 * Only the native Galaxy S9 panel (1440x2960) is changed.
 * All external-output properties are preserved from the active
 * base configuration.
 */

template<typename Output>
bool s9_is_phone_panel(
    Output const& output)
{
    for (auto const& mode : output.modes)
    {
        if (mode.size.width.as_int() == 1440 &&
            mode.size.height.as_int() == 2960)
        {
            return true;
        }
    }

    return false;
}


bool s9_parse_orientation(
    std::string command,
    MirOrientation& orientation)
{
    command = lower(command);

    while (!command.empty() &&
           (command.back() == '\n' ||
            command.back() == '\r' ||
            command.back() == ' ' ||
            command.back() == '\t'))
    {
        command.pop_back();
    }

    if (command == "portrait" ||
        command == "normal")
    {
        orientation = mir_orientation_normal;
        return true;
    }

    if (command == "landscape-right" ||
        command == "right")
    {
        orientation = mir_orientation_right;
        return true;
    }

    if (command == "landscape-left" ||
        command == "left")
    {
        orientation = mir_orientation_left;
        return true;
    }

    if (command == "portrait-inverted" ||
        command == "inverted")
    {
        orientation = mir_orientation_inverted;
        return true;
    }

    return false;
}


void s9_apply_runtime_orientation(
    std::shared_ptr<mir::shell::DisplayConfigurationController> const& controller,
    MirOrientation orientation,
    std::string const& command)
{
    try
    {
        auto const current = controller->base_configuration();

        if (!current)
        {
            std::cerr
                << "TASK12N ERROR: base_configuration is null"
                << std::endl;
            return;
        }

        auto cloned_unique = current->clone();

        auto configuration =
            std::shared_ptr<mg::DisplayConfiguration>{
                cloned_unique.release()};

        bool found_phone = false;
        bool changed = false;

        configuration->for_each_output(
            [&](mg::UserDisplayConfigurationOutput& output)
            {
                if (!output.connected ||
                    !s9_is_phone_panel(output))
                    return;

                /*
                 * Absolutely nothing else is modified here.
                 *
                 * Task12M remains responsible for:
                 *   - DP adaptive mode
                 *   - DP primary geometry
                 *   - phone position
                 *   - Samsung HWC compatibility
                 */
                found_phone = true;

                if (output.orientation == orientation)
                {
                    std::cerr
                        << "TASK12N NOOP: command="
                        << command
                        << " orientation already active"
                        << std::endl;
                    return;
                }

                output.orientation = orientation;
                changed = true;

                std::cerr
                    << "TASK12N APPLY: command="
                    << command
                    << " output=PHONE"
                    << " pos=+"
                    << output.top_left.x.as_int()
                    << "+"
                    << output.top_left.y.as_int()
                    << std::endl;
            });

        if (!found_phone)
        {
            std::cerr
                << "TASK12N ERROR: native 1440x2960 phone panel not found"
                << std::endl;
            return;
        }

        if (!changed)
        {
            return;
        }

        controller->set_base_configuration(configuration);

        std::cerr
            << "TASK12N APPLIED: "
            << command
            << std::endl;
    }
    catch (std::exception const& e)
    {
        std::cerr
            << "TASK12N EXCEPTION: "
            << e.what()
            << std::endl;
    }
}


void s9_runtime_orientation_control(mir::Server& server)
{
    /*
     * The DisplayConfigurationController is only available after
     * Mir initialization, so create the control worker from the
     * init callback.
     */
    server.add_init_callback(
        [&server]
        {
            auto const controller =
                server.the_display_configuration_controller();

            std::thread{
                [controller]
                {
                    char const* const path =
                        "/run/s9-displayctl";

                    ::unlink(path);

                    if (::mkfifo(path, 0666) != 0 &&
                        errno != EEXIST)
                    {
                        std::cerr
                            << "TASK12N ERROR: mkfifo("
                            << path
                            << "): "
                            << std::strerror(errno)
                            << std::endl;
                        return;
                    }

                    /*
                     * Do not let the service's umask make the control
                     * unavailable to the XFCE user.
                     */
                    ::chmod(path, 0666);

                    std::cerr
                        << "TASK12N READY: "
                        << path
                        << std::endl;

                    for (;;)
                    {
                        std::ifstream input{path};

                        if (!input)
                        {
                            std::cerr
                                << "TASK12N ERROR: cannot open "
                                << path
                                << std::endl;

                            ::sleep(1);
                            continue;
                        }

                        std::string command;

                        while (std::getline(input, command))
                        {
                            if (command.empty())
                                continue;

                            MirOrientation orientation;

                            if (!s9_parse_orientation(
                                    command,
                                    orientation))
                            {
                                std::cerr
                                    << "TASK12N INVALID COMMAND: "
                                    << command
                                    << std::endl;
                                continue;
                            }

                            s9_apply_runtime_orientation(
                                controller,
                                orientation,
                                command);
                        }
                    }
                }}.detach();
        });
}

}

// ---- S9 V33: inverte o scroll vertical do mouse (escala -1) ----
namespace
{
double s9v33_scroll_scale()
{
    char const* const env = std::getenv("S9_SCROLL_SCALE");
    if (env && *env)
    {
        char* end = nullptr;
        double const v = std::strtod(env, &end);
        if (end && *end == '\0')
            return v;
    }
    return -1.0;
}
}

void s9_scroll_control(mir::Server& server)
{
    server.add_init_callback(
        [&server]
        {
            auto const hub = server.the_input_device_hub();
            double const scale = s9v33_scroll_scale();
            std::cerr << "S9-SCROLL: ativo, escala alvo = " << scale << std::endl;
            std::thread{
                [hub, scale]
                {
                    auto attempts = std::make_shared<std::map<int, int>>();
                    for (;;)
                    {
                        std::this_thread::sleep_for(std::chrono::seconds(3));
                        hub->for_each_mutable_input_device(
                            [scale, attempts](mir::input::Device& dev)
                            {
#ifdef S9V33_TPD
                                if (dev.touchpad_configuration().is_set())
                                    return;
#else
                                {
                                    auto n = dev.name();
                                    for (auto& ch : n)
                                        ch = static_cast<char>(::tolower(static_cast<unsigned char>(ch)));
                                    if (n.find("touchpad") != std::string::npos)
                                        return;
                                }
#endif
                                auto const pc = dev.pointer_configuration();
                                if (!pc.is_set())
                                    return;
                                MirPointerConfig conf{pc.value()};
                                if (conf.vertical_scroll_scale() == scale)
                                    return;
                                int const id = static_cast<int>(dev.id());
                                if ((*attempts)[id] >= 3)
                                    return;
                                ++(*attempts)[id];
                                conf.vertical_scroll_scale(scale);
                                dev.apply_pointer_configuration(conf);
                                std::cerr << "S9-SCROLL: '" << dev.name() << "' id=" << id
                                          << " vscroll_scale -> " << scale
                                          << " (tentativa " << (*attempts)[id] << ")" << std::endl;
                            });
                    }
                }}.detach();
        });
}

// ---- S9 V34: reforço do keymap quando o teclado aparece tarde (boot) ----
void s9_kbd_control(mir::Server& server, miral::Keymap keymap)
{
    server.add_init_callback(
        [&server, keymap]
        {
            std::remove("/run/s9-miral/kbd-ready");
            auto const hub = server.the_input_device_hub();
            std::thread{
                [hub, keymap]() mutable
                {
                    using clock = std::chrono::steady_clock;
                    struct Seen { clock::time_point first; int pokes; clock::time_point last_log; };
                    struct Kb { int id; std::string name; std::string layout; };

                    std::map<int, Seen> seen;
                    bool ready_flag_written = false;
                    auto const t0 = clock::now();
                    auto const since = [t0](clock::time_point t)
                        { return std::chrono::duration_cast<std::chrono::milliseconds>(t - t0).count(); };
                    std::cerr << "S9-KBD: ativo, layout alvo = br" << std::endl;

                    for (;;)
                    {
                        std::this_thread::sleep_for(std::chrono::seconds(1));

                        auto kbds = std::make_shared<std::vector<Kb>>();
                        hub->for_each_input_device(
                            [kbds](mir::input::Device const& dev)
                            {
                                auto const kc = dev.keyboard_configuration();
                                if (!kc.is_set())
                                    return;
                                std::string layout{"?"};
#ifdef S9V34_KBDREAD
                                layout = kc.value().device_keymap().layout;
#endif
                                kbds->push_back(Kb{static_cast<int>(dev.id()), dev.name(), layout});
                            });

                        auto const now = clock::now();
                        bool poke = false;
                        for (auto const& k : *kbds)
                        {
                            auto it = seen.find(k.id);
                            if (it == seen.end())
                            {
                                seen[k.id] = Seen{now, 0, now};
                                std::cerr << "S9-KBD: +" << since(now) << "ms teclado id=" << k.id
                                          << " '" << k.name << "' layout=" << k.layout << std::endl;
                                continue;
                            }
                            auto& s = it->second;
                            auto const age = std::chrono::duration_cast<std::chrono::milliseconds>(now - s.first).count();
                            if ((s.pokes == 0 && age >= 3000) || (s.pokes == 1 && age >= 10000))
                            {
                                ++s.pokes;
                                poke = true;
                                std::cerr << "S9-KBD: +" << since(now) << "ms reaplicando teclado (id=" << k.id
                                          << " layout=" << k.layout << " tentativa " << s.pokes << ")" << std::endl;
                            }
                            else if (s.pokes >= 2 && k.layout != s9cfg::layout() && k.layout != "?" &&
                                     std::chrono::duration_cast<std::chrono::seconds>(now - s.last_log).count() >= 30)
                            {
                                s.last_log = now;
                                std::cerr << "S9-KBD: +" << since(now) << "ms AVISO id=" << k.id
                                          << " layout=" << k.layout << " (esperado " << s9cfg::layout() << ")" << std::endl;
                            }
                        }
                        if (poke)
                        {
                            keymap.set_keymap(s9cfg::poke_alt());
                            std::this_thread::sleep_for(std::chrono::milliseconds(300));
                            keymap.set_keymap(s9cfg::keymap_full());
                            if (!ready_flag_written)
                            {
                                std::this_thread::sleep_for(std::chrono::milliseconds(1500));
                                std::ofstream flag("/run/s9-miral/kbd-ready");
                                flag << "ok\n";
                                flag.close();
                                ready_flag_written = true;
                                std::cerr << "S9-KBD: +" << since(clock::now()) << "ms flag kbd-ready criado" << std::endl;
                            }
                        }
                    }
                }}.detach();
        });
}

int main(int argc, char const* argv[])
{
    using namespace miral;

    MirRunner runner{argc, argv};

    ExternalClientLauncher external_client_launcher;

    WindowManagerOptions window_manager
    {
        add_window_manager_policy<S9WindowManager>("s9")
    };

    /*
     * Deliberately NO:
     *
     *   SpinnerSplash
     *   StartupInternalClient{spinner}
     *   wallpaper client
     *   DecorationProvider
     *   xfwm4
     *
     * XFCE itself will supply xfdesktop and xfce4-panel.
     */
    Keymap keymap{s9cfg::keymap_full()};
    std::cerr << "S9_CONFIG_V1 usuario=" << s9cfg::user() << " keymap=" << s9cfg::keymap_full() << std::endl;
    auto const kbd_fix = [keymap](mir::Server& server) { s9_kbd_control(server, keymap); };

    return runner.run_with(
    {
        CursorTheme{"default"},
        WaylandExtensions{},
        X11Support{},
        keymap,
        window_manager,
        display_configuration_options,
        s9_display_policy,
        s9_runtime_orientation_control,
        s9_scroll_control,
        kbd_fix,
        external_client_launcher
    });
}
