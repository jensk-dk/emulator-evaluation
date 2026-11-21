/*
 * RDK's reference user interface shows its first-run steps (pair a remote
 * control, choose a language, set up the network) until it has once reached
 * its Home screen, which it notes in the browser's storage. The emulator
 * discards what a target wrote when it ends, so every start would be the
 * first. This marks the steps as done before the user interface starts.
 *
 * To see the first-run steps, open the page with "?firstrun" in its address:
 *   tvemu-app-start ResidentApp 'http://127.0.0.1:50050/lxresui/index.html?firstrun#splash'
 */
(function () {
    try {
        if (window.location.search.indexOf("firstrun") < 0) {
            // The key is the user interface's own: its platform id and "setup".
            window.localStorage.setItem("UIv3.setup", "true");
        } else {
            window.localStorage.removeItem("UIv3.setup");
        }
    } catch (error) {
        console.warn("tvemu-first-run: " + error);
    }
})();
