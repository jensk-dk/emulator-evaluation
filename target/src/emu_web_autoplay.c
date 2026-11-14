/* Lets the pages of the web-bench workload start media with sound.
 *
 * WPE WebKit starts media on its own only without sound, unless its embedder
 * gives a page the autoplay policy "allow". Cog, the launcher the workload
 * uses, has no option for that, and the target has nobody to click on the
 * page. This library is loaded into Cog ahead of WebKit's (LD_PRELOAD). It
 * steps in where Cog asks a web view to load a page, and has that view answer
 * its navigation decisions with a policy that allows autoplay. Everything is
 * WebKit's public interface; nothing else about the browser changes.
 *
 * Built by target/Dockerfile; used by target/rootfs/opt/emu/workloads/web-bench.
 */
#define _GNU_SOURCE

#include <dlfcn.h>
#include <wpe/webkit.h>

static gboolean decide(WebKitWebView *view, WebKitPolicyDecision *decision, WebKitPolicyDecisionType type,
                       gpointer data)
{
    (void)view;
    (void)data;
    if (type != WEBKIT_POLICY_DECISION_TYPE_NAVIGATION_ACTION)
        return FALSE;
    WebKitWebsitePolicies *policies =
        webkit_website_policies_new_with_policies("autoplay", WEBKIT_AUTOPLAY_ALLOW, NULL);
    webkit_policy_decision_use_with_policies(decision, policies);
    g_object_unref(policies);
    return TRUE;
}

void webkit_web_view_load_uri(WebKitWebView *view, const gchar *uri)
{
    static void (*load)(WebKitWebView *, const gchar *);
    if (!load)
        load = (void (*)(WebKitWebView *, const gchar *))dlsym(RTLD_NEXT, "webkit_web_view_load_uri");
    if (!g_object_get_data(G_OBJECT(view), "emu-autoplay")) {
        g_object_set_data(G_OBJECT(view), "emu-autoplay", GINT_TO_POINTER(1));
        g_signal_connect(view, "decide-policy", G_CALLBACK(decide), NULL);
    }
    if (load)
        load(view, uri);
}
