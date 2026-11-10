#!/bin/bash
# Compare only the INPUT files of a run across clusters, from the manifests
# c7_fleet.sh verify wrote to /tmp/c7v. Derived result summaries
# (*-dense-summary.json, *-functions-*-summary.json, ...) are outputs and
# are left out on purpose.
cd /tmp/c7v || exit 1
P="ambari beam camel cassandra derby drill flink geode groovy hadoop hbase hive ignite impala infinispan kafka keycloak mariadb mongodb pdfbox phoenix pig qt sakai solr spark wildfly"
pat="^bench/|^res/baseline-(sample|pilot)\.json |-noise-dump\.jsonl "
for p in $P; do pat="$pat|^res/$p-instances\.jsonl |^res/$p-summary\.json "; done
for h in laptop nibi fir rorqual trillium-gpu; do
  tail -n +2 $h.txt | grep -E "$pat" | LC_ALL=C sort > in_$h.txt
done
echo "laptop: $(wc -l < in_laptop.txt) input files, hash $(sha256sum < in_laptop.txt | cut -c1-16)"
for h in nibi fir rorqual trillium-gpu; do
  echo "$h: $(wc -l < in_$h.txt) input files, hash $(sha256sum < in_$h.txt | cut -c1-16), differing lines: $(diff in_laptop.txt in_$h.txt | grep -c '^[<>]')"
  diff in_laptop.txt in_$h.txt | grep '^[<>]' | head -6
done
