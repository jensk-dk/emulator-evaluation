/*
 * A stand-in for org.rdk.RDKShell on RDK-E's middleware.
 *
 * RDK-E has replaced org.rdk.RDKShell with org.rdk.RDKWindowManager, and its
 * applications are meant to be started by org.rdk.AppManager. RDK's reference
 * user interface up to its 5.x releases still starts every application with
 * org.rdk.RDKShell. This plug-in answers the calls that user interface makes
 * under that call sign, with the window manager and the plug-ins of the
 * applications themselves:
 *
 *   launch              a display from the window manager, the application's
 *                       plug-in activated on it, its address, the focus
 *   destroy, kill       the application's plug-in deactivated
 *   suspend             the plug-in suspended and its display hidden
 *   setVisibility, getVisibility, setFocus, the key intercepts and the
 *   inactivity calls    the window manager's calls of the same purpose
 *   getAvailableTypes, getClients, getZOrder, getState
 *                       answered from Thunder's plug-ins and the window
 *                       manager's displays
 *
 * The stacking order is not kept: moveToFront, moveToBack and moveBehind
 * answer with success and change nothing, as do the calls for opacity, scale,
 * bounds and animations. launchApplication (a native application) fails.
 *
 * Licensed under the Apache License, Version 2.0.
 */
#include "Module.h"

#include <interfaces/IBrowser.h>
#include <interfaces/IRDKWindowManager.h>

#include <algorithm>
#include <cstdio>
#include <fstream>

namespace WPEFramework {
namespace Plugin {

    namespace {
        const TCHAR* WindowManager = _T("org.rdk.RDKWindowManager");

        // The call signs the user interface may ask for. Those that this
        // Thunder has no plug-in for are left out of every answer.
        const TCHAR* Types[] = {
            _T("HtmlApp"), _T("LightningApp"), _T("ResidentApp"), _T("SearchAndDiscoveryApp"), _T("WebKitBrowser"),
            _T("Cobalt"), _T("YouTube"), _T("YouTubeTV"), _T("YouTubeKids"), _T("Netflix"), _T("Amazon"),
            _T("Peacock"), _T("FireboltApp")
        };

        // The window manager's name for an application: its call sign in
        // small letters, as in the plug-in's own configuration ("wst-" and
        // that name is the display the browser connects to).
        string ClientOf(const string& name)
        {
            string client(name);
            std::transform(client.begin(), client.end(), client.begin(), [](unsigned char c) { return std::tolower(c); });
            return client;
        }

        // The display mode the emulator gave the virtual machine.
        void DisplaySize(uint32_t& width, uint32_t& height)
        {
            width = 1920;
            height = 1080;
            std::ifstream modes("/sys/class/drm/card0-Virtual-1/modes");
            string mode;
            unsigned int w = 0, h = 0;
            if (std::getline(modes, mode) && (std::sscanf(mode.c_str(), "%ux%u", &w, &h) == 2) && (w > 0) && (h > 0)) {
                width = w;
                height = h;
            }
        }

        void Log(const char* what, const string& who, const uint32_t result)
        {
            std::fprintf(stderr, "TvemuRDKShell: %s %s: %s\n", what, who.c_str(),
                (result == Core::ERROR_NONE ? "done" : Core::ErrorToString(result)));
            std::fflush(stderr);
        }
    }

    class TvemuRDKShell : public PluginHost::IPlugin, public PluginHost::JSONRPC {
    public:
        TvemuRDKShell(const TvemuRDKShell&) = delete;
        TvemuRDKShell& operator=(const TvemuRDKShell&) = delete;

        TvemuRDKShell()
            : PluginHost::JSONRPC()
            , _service(nullptr)
        {
        }
        ~TvemuRDKShell() override = default;

        BEGIN_INTERFACE_MAP(TvemuRDKShell)
        INTERFACE_ENTRY(PluginHost::IPlugin)
        INTERFACE_ENTRY(PluginHost::IDispatcher)
        END_INTERFACE_MAP

        const string Initialize(PluginHost::IShell* service) override
        {
            ASSERT(service != nullptr);
            _service = service;
            _service->AddRef();

            Register<JsonObject, JsonObject>(_T("launch"), &TvemuRDKShell::Launch, this);
            Register<JsonObject, JsonObject>(_T("launchApplication"), &TvemuRDKShell::Refuse, this);
            Register<JsonObject, JsonObject>(_T("destroy"), &TvemuRDKShell::Destroy, this);
            Register<JsonObject, JsonObject>(_T("kill"), &TvemuRDKShell::Destroy, this);
            Register<JsonObject, JsonObject>(_T("suspend"), &TvemuRDKShell::Suspend, this);
            Register<JsonObject, JsonObject>(_T("setVisibility"), &TvemuRDKShell::SetVisibility, this);
            Register<JsonObject, JsonObject>(_T("getVisibility"), &TvemuRDKShell::GetVisibility, this);
            Register<JsonObject, JsonObject>(_T("setFocus"), &TvemuRDKShell::SetFocus, this);
            Register<JsonObject, JsonObject>(_T("getAvailableTypes"), &TvemuRDKShell::GetAvailableTypes, this);
            Register<JsonObject, JsonObject>(_T("getClients"), &TvemuRDKShell::GetClients, this);
            Register<JsonObject, JsonObject>(_T("getZOrder"), &TvemuRDKShell::GetClients, this);
            Register<JsonObject, JsonObject>(_T("getState"), &TvemuRDKShell::GetState, this);
            Register<JsonObject, JsonObject>(_T("addKeyIntercept"), &TvemuRDKShell::AddKeyIntercept, this);
            Register<JsonObject, JsonObject>(_T("addKeyIntercepts"), &TvemuRDKShell::AddKeyIntercepts, this);
            Register<JsonObject, JsonObject>(_T("removeKeyIntercept"), &TvemuRDKShell::RemoveKeyIntercept, this);
            Register<JsonObject, JsonObject>(_T("enableInactivityReporting"), &TvemuRDKShell::EnableInactivityReporting, this);
            Register<JsonObject, JsonObject>(_T("setInactivityInterval"), &TvemuRDKShell::SetInactivityInterval, this);
            Register<JsonObject, JsonObject>(_T("resetInactivityTime"), &TvemuRDKShell::ResetInactivityTime, this);
            for (const TCHAR* name : { _T("moveToFront"), _T("moveToBack"), _T("moveBehind"), _T("setOpacity"),
                     _T("setScale"), _T("setBounds"), _T("addAnimation"), _T("removeAnimation"), _T("hideSplashLogo"),
                     _T("hideFullScreenImage"), _T("restore"), _T("enableKeyRepeats"), _T("removeAllKeyIntercepts") }) {
                Register<JsonObject, JsonObject>(name, &TvemuRDKShell::Accept, this);
            }
            return (string());
        }

        void Deinitialize(PluginHost::IShell* service) override
        {
            ASSERT(service == _service);
            for (const TCHAR* name : { _T("launch"), _T("launchApplication"), _T("destroy"), _T("kill"), _T("suspend"),
                     _T("setVisibility"), _T("getVisibility"), _T("setFocus"), _T("getAvailableTypes"), _T("getClients"),
                     _T("getZOrder"), _T("getState"), _T("addKeyIntercept"), _T("addKeyIntercepts"),
                     _T("removeKeyIntercept"), _T("enableInactivityReporting"), _T("setInactivityInterval"),
                     _T("resetInactivityTime"), _T("moveToFront"), _T("moveToBack"), _T("moveBehind"),
                     _T("setOpacity"), _T("setScale"), _T("setBounds"), _T("addAnimation"), _T("removeAnimation"),
                     _T("hideSplashLogo"), _T("hideFullScreenImage"), _T("restore"), _T("enableKeyRepeats"),
                     _T("removeAllKeyIntercepts") }) {
                Unregister(name);
            }
            _service->Release();
            _service = nullptr;
        }

        string Information() const override
        {
            return (string());
        }

    private:
        // The application a call is about: "callsign", or "client" where the
        // caller gave only that.
        static string Named(const JsonObject& parameters)
        {
            if (parameters.HasLabel("callsign") && (parameters["callsign"].String().empty() == false)) {
                return (parameters["callsign"].String());
            }
            return (parameters.HasLabel("client") ? parameters["client"].String() : string());
        }

        static uint32_t Answer(JsonObject& response, const uint32_t result)
        {
            response["success"] = (result == Core::ERROR_NONE);
            // The user interface reads "success"; a JSON-RPC error would
            // reach it as an exception with no cause.
            return (Core::ERROR_NONE);
        }

        Exchange::IRDKWindowManager* Windows() const
        {
            return (_service->QueryInterfaceByCallsign<Exchange::IRDKWindowManager>(WindowManager));
        }

        PluginHost::IShell* PluginOf(const string& callsign) const
        {
            return (callsign.empty() ? nullptr : _service->QueryInterfaceByCallsign<PluginHost::IShell>(callsign));
        }

        bool HasDisplay(Exchange::IRDKWindowManager* windows, const string& client) const
        {
            bool found = false;
            Exchange::IRDKWindowManager::IStringIterator* apps = nullptr;
            if ((windows->GetApps(apps) == Core::ERROR_NONE) && (apps != nullptr)) {
                string name;
                while (apps->Next(name) == true) {
                    found = found || (name == client);
                }
                apps->Release();
            }
            return (found);
        }

        uint32_t Launch(const JsonObject& parameters, JsonObject& response)
        {
            const string callsign(Named(parameters));
            const string client(ClientOf(callsign));
            const string address(parameters.HasLabel("uri") ? parameters["uri"].String() : string());
            uint32_t result = Core::ERROR_UNKNOWN_KEY;
            bool resumed = false;

            PluginHost::IShell* plugin = PluginOf(callsign);
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows == nullptr) {
                result = Core::ERROR_UNAVAILABLE;
            } else if (plugin != nullptr) {
                result = Core::ERROR_NONE;
                if (HasDisplay(windows, client) == false) {
                    uint32_t width, height;
                    DisplaySize(width, height);
                    result = windows->CreateDisplay(client, "wst-" + client, width, height, false, 0, 0, 0, 0, false,
                        true, string());
                    Log("display for", client, result);
                }
                if (result == Core::ERROR_NONE) {
                    resumed = (plugin->State() == PluginHost::IShell::ACTIVATED);
                    if (resumed == false) {
                        result = plugin->Activate(PluginHost::IShell::REQUESTED);
                        Log("activate", callsign, result);
                    }
                }
                if (result == Core::ERROR_NONE) {
                    PluginHost::IStateControl* control = _service->QueryInterfaceByCallsign<PluginHost::IStateControl>(callsign);
                    if (control != nullptr) {
                        control->Request(PluginHost::IStateControl::RESUME);
                        control->Release();
                    }
                    if (address.empty() == false) {
                        Exchange::IWebBrowser* browser = _service->QueryInterfaceByCallsign<Exchange::IWebBrowser>(callsign);
                        if (browser != nullptr) {
                            result = browser->URL(address);
                            browser->Release();
                        } else {
                            result = Core::ERROR_UNAVAILABLE;
                        }
                        Log("address for", callsign, result);
                    }
                    windows->SetFocus(client);
                    windows->SetVisible(client, true);
                }
            }
            if (windows != nullptr) {
                windows->Release();
            }
            if (plugin != nullptr) {
                plugin->Release();
            }
            Log("launch", callsign, result);
            if (result == Core::ERROR_NONE) {
                response["launchType"] = (resumed ? "resume" : "activate");
                JsonObject event;
                event["client"] = callsign;
                event["launchType"] = (resumed ? "resume" : "activate");
                Notify(_T("onLaunched"), event);
            } else {
                response["message"] = Core::ErrorToString(result);
            }
            return (Answer(response, result));
        }

        uint32_t Destroy(const JsonObject& parameters, JsonObject& response)
        {
            const string callsign(Named(parameters));
            uint32_t result = Core::ERROR_UNKNOWN_KEY;
            PluginHost::IShell* plugin = PluginOf(callsign);
            if (plugin != nullptr) {
                // The display goes with the browser that was connected to it.
                result = plugin->Deactivate(PluginHost::IShell::REQUESTED);
                plugin->Release();
            }
            Log("destroy", callsign, result);
            if (result == Core::ERROR_NONE) {
                JsonObject event;
                event["client"] = callsign;
                Notify(_T("onDestroyed"), event);
            }
            return (Answer(response, result));
        }

        uint32_t Suspend(const JsonObject& parameters, JsonObject& response)
        {
            const string callsign(Named(parameters));
            uint32_t result = Core::ERROR_UNKNOWN_KEY;
            PluginHost::IStateControl* control = (callsign.empty() ? nullptr : _service->QueryInterfaceByCallsign<PluginHost::IStateControl>(callsign));
            if (control != nullptr) {
                result = control->Request(PluginHost::IStateControl::SUSPEND);
                control->Release();
                Exchange::IRDKWindowManager* windows = Windows();
                if (windows != nullptr) {
                    windows->SetVisible(ClientOf(callsign), false);
                    windows->Release();
                }
            }
            Log("suspend", callsign, result);
            if (result == Core::ERROR_NONE) {
                JsonObject event;
                event["client"] = callsign;
                Notify(_T("onSuspended"), event);
            }
            return (Answer(response, result));
        }

        uint32_t SetVisibility(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                const string client(ClientOf(parameters.HasLabel("client") ? parameters["client"].String() : Named(parameters)));
                result = windows->SetVisible(client, parameters["visible"].Boolean());
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t GetVisibility(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                bool visible = false;
                const string client(ClientOf(parameters.HasLabel("client") ? parameters["client"].String() : Named(parameters)));
                result = windows->GetVisibility(client, visible);
                response["visible"] = visible;
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t SetFocus(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                const string client(ClientOf(parameters.HasLabel("client") ? parameters["client"].String() : Named(parameters)));
                result = windows->SetFocus(client);
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t GetAvailableTypes(const JsonObject&, JsonObject& response)
        {
            JsonArray types;
            for (const TCHAR* name : Types) {
                PluginHost::IShell* plugin = PluginOf(name);
                if (plugin != nullptr) {
                    types.Add(JsonValue(string(name)));
                    plugin->Release();
                }
            }
            response["types"] = types;
            return (Answer(response, Core::ERROR_NONE));
        }

        uint32_t GetClients(const JsonObject&, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            JsonArray clients;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                Exchange::IRDKWindowManager::IStringIterator* apps = nullptr;
                result = windows->GetApps(apps);
                if ((result == Core::ERROR_NONE) && (apps != nullptr)) {
                    string name;
                    while (apps->Next(name) == true) {
                        clients.Add(JsonValue(name));
                    }
                    apps->Release();
                }
                windows->Release();
            }
            response["clients"] = clients;
            return (Answer(response, result));
        }

        uint32_t GetState(const JsonObject&, JsonObject& response)
        {
            JsonArray states;
            for (const TCHAR* name : Types) {
                PluginHost::IShell* plugin = PluginOf(name);
                if (plugin != nullptr) {
                    if (plugin->State() == PluginHost::IShell::ACTIVATED) {
                        JsonObject entry;
                        string address;
                        bool suspended = false;
                        PluginHost::IStateControl* control = _service->QueryInterfaceByCallsign<PluginHost::IStateControl>(name);
                        if (control != nullptr) {
                            suspended = (control->State() == PluginHost::IStateControl::SUSPENDED);
                            control->Release();
                        }
                        Exchange::IWebBrowser* browser = _service->QueryInterfaceByCallsign<Exchange::IWebBrowser>(name);
                        if (browser != nullptr) {
                            static_cast<const Exchange::IWebBrowser*>(browser)->URL(address);
                            browser->Release();
                        }
                        entry["callsign"] = string(name);
                        entry["state"] = (suspended ? "suspended" : "resumed");
                        entry["uri"] = address;
                        states.Add(JsonValue(entry));
                    }
                    plugin->Release();
                }
            }
            response["state"] = states;
            return (Answer(response, Core::ERROR_NONE));
        }

        uint32_t AddKeyIntercept(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                JsonObject intercept;
                string text;
                parameters.ToString(text);
                intercept.FromString(text);
                intercept["client"] = ClientOf(Named(parameters));
                intercept.ToString(text);
                result = windows->AddKeyIntercept(text);
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t AddKeyIntercepts(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                result = Core::ERROR_NONE;
                const JsonArray intercepts(parameters["intercepts"].Array());
                for (uint16_t index = 0; index < intercepts.Length(); index++) {
                    const JsonObject entry(intercepts[index].Object());
                    const string client(ClientOf(Named(entry)));
                    string keys;
                    entry["keys"].Array().ToString(keys);
                    const uint32_t added = windows->AddKeyIntercepts(client, keys);
                    Log("key intercepts for", client, added);
                    if (added != Core::ERROR_NONE) {
                        result = added;
                    }
                }
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t RemoveKeyIntercept(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                string modifiers(_T("[]"));
                if (parameters.HasLabel("modifiers")) {
                    parameters["modifiers"].Array().ToString(modifiers);
                }
                result = windows->RemoveKeyIntercept(ClientOf(Named(parameters)),
                    static_cast<uint32_t>(parameters["keyCode"].Number()), modifiers);
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t EnableInactivityReporting(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                result = windows->EnableInactivityReporting(parameters["enable"].Boolean());
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t SetInactivityInterval(const JsonObject& parameters, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                result = windows->SetInactivityInterval(static_cast<uint32_t>(parameters["interval"].Number()));
                windows->Release();
            }
            return (Answer(response, result));
        }

        uint32_t ResetInactivityTime(const JsonObject&, JsonObject& response)
        {
            uint32_t result = Core::ERROR_UNAVAILABLE;
            Exchange::IRDKWindowManager* windows = Windows();
            if (windows != nullptr) {
                result = windows->ResetInactivityTime();
                windows->Release();
            }
            return (Answer(response, result));
        }

        // Calls that have nothing to change here.
        uint32_t Accept(const JsonObject&, JsonObject& response)
        {
            return (Answer(response, Core::ERROR_NONE));
        }

        uint32_t Refuse(const JsonObject&, JsonObject& response)
        {
            response["message"] = "not available on the emulator";
            return (Answer(response, Core::ERROR_UNAVAILABLE));
        }

    private:
        PluginHost::IShell* _service;
    };

    namespace {
        static Metadata<TvemuRDKShell> metadata(1, 0, 0, {}, {}, {});
    }

    SERVICE_REGISTRATION(TvemuRDKShell, 1, 0, 0);

} // namespace Plugin
} // namespace WPEFramework
