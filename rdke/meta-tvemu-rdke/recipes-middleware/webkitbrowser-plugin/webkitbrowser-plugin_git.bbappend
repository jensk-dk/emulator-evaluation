# The browser plug-in's bindings for AAMP, RDK's player for HLS and DASH, need
# AAMP built, and AAMP's build misses a library here (libbaseconversion, of
# RDK's player interface). The player is left for later; the browser does not
# need it to show pages or to play media itself.
PACKAGECONFIG:remove:tvemu = "aampjsbindings"
