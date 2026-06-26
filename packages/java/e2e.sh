#!/usr/bin/env bash
# End-to-end test for the JVM capture -> replay pipeline.
# Run after `mvn -DskipTests package` (needs target/selfsame.jar).
#
#   bash e2e.sh
#
# Builds two versions of a sample class, captures real inputs by running a driver
# under the agent, replays the captures against both versions, and asserts that a
# real behavior change is caught (and that identical code is reported equivalent).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
JAR="$HERE/target/selfsame.jar"
[ -f "$JAR" ] || { echo "FAIL: $JAR not found (run: mvn -DskipTests package)"; exit 1; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/v1" "$T/v2"

cat > "$T/v1/Calc.java" <<'JAVA'
public class Calc { public static long applyDiscount(long price, int pct){ return Math.round(price*(1-pct/100.0)); } }
JAVA
cat > "$T/v1/Main.java" <<'JAVA'
public class Main { public static void main(String[] a){
  for (int[] in : new int[][]{{100,10},{101,10},{3,10},{50,50}}) Calc.applyDiscount(in[0], in[1]);
}}
JAVA
cat > "$T/v2/Calc.java" <<'JAVA'
public class Calc { public static long applyDiscount(long price, int pct){ return (long)Math.floor(price*(1-pct/100.0)); } }
JAVA

javac -d "$T/before" "$T/v1/Calc.java" "$T/v1/Main.java"
javac -d "$T/after"  "$T/v2/Calc.java"

java -jar "$JAR" capture --target Calc --cp "$T/before" --out "$T/caps" --main Main >/dev/null
[ -f "$T/caps/captures.json" ] || { echo "FAIL: no captures produced"; exit 1; }

fail=0

# 1. a real behavior change must be caught (exit 1, 'divergent')
out="$(java -jar "$JAR" replay --before "$T/before" --after "$T/after" --captures "$T/caps")"; code=$?
echo "$out"
if [ "$code" = "1" ] && echo "$out" | grep -q "divergent"; then
  echo "PASS: divergence caught"
else
  echo "FAIL: expected exit 1 + divergent (got exit $code)"; fail=1
fi

# 2. identical code must be equivalent (exit 0, no false positive)
out="$(java -jar "$JAR" replay --before "$T/before" --after "$T/before" --captures "$T/caps")"; code=$?
if [ "$code" = "0" ] && echo "$out" | grep -q "equivalent"; then
  echo "PASS: identical code equivalent"
else
  echo "FAIL: expected exit 0 + equivalent (got exit $code)"; fail=1
fi

[ "$fail" = "0" ] && echo "e2e OK" || { echo "e2e FAILED"; exit 1; }
