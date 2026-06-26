#!/usr/bin/env bash
# End-to-end test for the JVM capture -> replay pipeline (static + instance methods).
# Run after `mvn -DskipTests package` (needs target/selfsame.jar).
#
#   bash e2e.sh
#
# Builds two versions of a sample package, captures real inputs by running a
# driver under the agent, replays against both versions, and asserts that real
# behavior changes are caught (and identical code is reported equivalent).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
JAR="$HERE/target/selfsame.jar"
[ -f "$JAR" ] || { echo "FAIL: $JAR not found (run: mvn -DskipTests package)"; exit 1; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/v1/shop" "$T/v2/shop"

# v1
cat > "$T/v1/shop/Pricing.java" <<'JAVA'
package shop;
public class Pricing { public static long applyDiscount(long price, int pct){ return Math.round(price*(1-pct/100.0)); } }
JAVA
cat > "$T/v1/shop/Account.java" <<'JAVA'
package shop;
public class Account { private long balance; public Account(long b){ this.balance=b; }
  public long withdraw(int amt){ balance -= amt; return balance; } }
JAVA
cat > "$T/v1/shop/Main.java" <<'JAVA'
package shop;
public class Main { public static void main(String[] a){
  for (int[] in : new int[][]{{100,10},{101,10},{3,10}}) Pricing.applyDiscount(in[0], in[1]);
  Account acc = new Account(100); acc.withdraw(30); acc.withdraw(20);
}}
JAVA
# v2: floor pricing + a withdrawal fee (both behavior changes)
cat > "$T/v2/shop/Pricing.java" <<'JAVA'
package shop;
public class Pricing { public static long applyDiscount(long price, int pct){ return (long)Math.floor(price*(1-pct/100.0)); } }
JAVA
cat > "$T/v2/shop/Account.java" <<'JAVA'
package shop;
public class Account { private long balance; public Account(long b){ this.balance=b; }
  public long withdraw(int amt){ balance -= amt + 1; return balance; } }
JAVA

javac -d "$T/before" "$T/v1/shop/"*.java
javac -d "$T/after"  "$T/v2/shop/Pricing.java" "$T/v2/shop/Account.java"

java -jar "$JAR" capture --target shop --cp "$T/before" --out "$T/caps" --main shop.Main >/dev/null
[ -f "$T/caps/captures.json" ] || { echo "FAIL: no captures produced"; exit 1; }

fail=0

out="$(java -jar "$JAR" replay --before "$T/before" --after "$T/after" --captures "$T/caps")"; code=$?
echo "$out"
# both the static method (round->floor) and the instance method (fee) must diverge
if [ "$code" = "1" ] && echo "$out" | grep -q "applyDiscount.*divergent" && echo "$out" | grep -q "withdraw.*divergent"; then
  echo "PASS: static + instance divergences caught"
else
  echo "FAIL: expected exit 1 with applyDiscount + withdraw divergent (exit $code)"; fail=1
fi

out="$(java -jar "$JAR" replay --before "$T/before" --after "$T/before" --captures "$T/caps")"; code=$?
if [ "$code" = "0" ] && ! echo "$out" | grep -q "divergent"; then
  echo "PASS: identical code equivalent"
else
  echo "FAIL: expected exit 0 + no divergence (exit $code)"; fail=1
fi

[ "$fail" = "0" ] && echo "e2e OK" || { echo "e2e FAILED"; exit 1; }
