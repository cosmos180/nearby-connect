#!/usr/bin/env python3
"""Build with the installed Android SDK; no Gradle or dependency downloads."""
import hashlib
import secrets
import os
from pathlib import Path
import shutil
import subprocess

import zipfile

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Android/Sdk")))
java_home = os.environ.get("JAVA_HOME") or os.environ.get("NEARBY_JAVA_HOME")
if not java_home and not shutil.which("javac"):
    raise SystemExit("Set JAVA_HOME to a JDK 17 installation")
JDK = Path(java_home) if java_home else Path(shutil.which("javac")).resolve().parents[1]
TOOLS = SDK / "build-tools/35.0.0"
PLATFORM = SDK / "platforms/android-35/android.jar"
BUILD = ROOT / "build"
ZXING = ROOT / "android/libs/core-3.3.2.jar"
KEYDIR = Path.home() / ".local/share/nearby-connect/release-signing"
SIGNING = KEYDIR / "release.p12"
PASSWORD = KEYDIR / "password"


def run(args):
    subprocess.run([str(arg) for arg in args], check=True,
                   env={**os.environ, "JAVA_HOME": str(JDK), "PATH": str(JDK / "bin") + ":" + os.environ["PATH"]})


def main():
    BUILD.mkdir(exist_ok=True)
    for folder in ("generated", "classes", "dex"):
        path = BUILD / folder
        if path.exists():
            shutil.rmtree(path)
        path.mkdir()
    unsigned = BUILD / "unsigned.apk"
    run([TOOLS / "aapt", "package", "-f", "-m", "-M", ROOT / "android/AndroidManifest.xml",
         "-S", ROOT / "android/res", "-I", PLATFORM, "-J", BUILD / "generated", "-F", unsigned])
    sources = sorted((ROOT / "android/src").rglob("*.java")) + sorted((BUILD / "generated").rglob("*.java"))
    run([JDK / "bin/javac", "-encoding", "UTF-8", "--release", "8", "-classpath", os.pathsep.join(map(str, (PLATFORM, ZXING))),
         "-d", BUILD / "classes", *sources])
    class_jar = BUILD / "classes.jar"
    with zipfile.ZipFile(class_jar, "w") as archive:
        for file in (BUILD / "classes").rglob("*.class"):
            archive.write(file, str(file.relative_to(BUILD / "classes")))
    run([TOOLS / "d8", "--lib", PLATFORM, "--min-api", "26", "--output", BUILD / "dex", class_jar, ZXING])
    with zipfile.ZipFile(unsigned, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(BUILD / "dex/classes.dex", "classes.dex")
    aligned = BUILD / "aligned.apk"
    run([TOOLS / "zipalign", "-f", "4", unsigned, aligned])
    KEYDIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not PASSWORD.exists():
        if SIGNING.exists():
            raise SystemExit("Signing password file missing")
        with open(os.open(PASSWORD, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
    if not SIGNING.exists():
        run([JDK / "bin/keytool", "-genkeypair", "-keystore", SIGNING, "-storepass:file", PASSWORD,
             "-keypass:file", PASSWORD, "-alias", "nearby", "-keyalg", "RSA", "-keysize", "3072",
             "-validity", "3650", "-dname", "CN=Nearby Connect"])
        SIGNING.chmod(0o600)
    apk = BUILD / "nearby-connect.apk"
    run([TOOLS / "apksigner", "sign", "--ks", SIGNING, "--ks-key-alias", "nearby",
         "--ks-pass", "file:" + str(PASSWORD), "--out", apk, aligned])
    run([TOOLS / "apksigner", "verify", "--verbose", apk])
    digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    (BUILD / "SHA256SUMS").write_text(digest + "  " + apk.name + "\n")
    print(f"APK: {apk}\nSHA256: {digest}")


if __name__ == "__main__":
    main()
