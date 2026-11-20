# 64-bit programs: the recipe unpacks a package of the agent that its makers
# built for 32-bit ARM (..._rdk_armv7.ipk), and the build refuses a 32-bit
# program in a 64-bit package. The same release has one built for ARM64.
SRC_URI:aarch64 = "https://github.com/xmidt-org/xmidt-agent/releases/download/v${PKG_VERSION}/xmidt-agent_${PKG_VERSION}_rdk_arm64.ipk;name=xmidt-agent-arm64"
SRC_URI[xmidt-agent-arm64.md5sum] = "e7d188bc53aebd7a065cda34dd80c557"
SRC_URI[xmidt-agent-arm64.sha256sum] = "619afe2f03f23876e7229392dd782e60f9f95b828bcdffcd95094d56a3584c98"

do_unpack:aarch64() {
    cd ${DL_DIR}
    tar -xvf xmidt-agent_${PKG_VERSION}_rdk_arm64.ipk -C ${S}
}
