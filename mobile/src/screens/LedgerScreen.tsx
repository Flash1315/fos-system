import React, { useEffect, useRef, useState } from "react";
import { Alert, FlatList, Pressable, RefreshControl, Text, StyleSheet, View } from "react-native";
import { listMembers, onResumeRefresh, orgRecords, type MoneyRecord, type User } from "../api";
import { Btn, Chip, Field, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { hasMorePage, mergeById } from "../listUtil";
import { colors } from "../theme";

export function LedgerScreen({
  onBack,
  onRecord,
}: {
  onBack: () => void;
  onRecord: (id: number) => void;
}) {
  const [rows, setRows] = useState<MoneyRecord[]>([]);
  const [members, setMembers] = useState<User[]>([]);
  const [status, setStatus] = useState<"" | "pending" | "approved" | "rejected" | "voided">("");
  const [kind, setKind] = useState<"" | "expense" | "fuel" | "income">("");
  const [purpose, setPurpose] = useState("");
  const [memberId, setMemberId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [membersError, setMembersError] = useState("");
  const reloadGen = useRef(0);
  const membersGen = useRef(0);
  const PAGE = 40;

  useEffect(() => {
    const t = setTimeout(() => setSearchDebounced(search.trim().slice(0, 80)), 350);
    return () => clearTimeout(t);
  }, [search]);

  const loadMembers = async () => {
    const gen = ++membersGen.current;
    try {
      setMembersError("");
      const next = await listMembers();
      if (gen !== membersGen.current) return;
      setMembers(next);
    } catch (e) {
      if (gen !== membersGen.current) return;
      // Keep last-known teammate filter choices on a transient directory blip.
      setMembersError(e instanceof Error ? e.message : "Failed to load teammates");
    }
  };

  useEffect(() => {
    void loadMembers();
  }, []);

  const listParams = () => ({
    status: status && status !== "voided" ? status : undefined,
    kind: kind || undefined,
    purpose: purpose || undefined,
    created_by: memberId ?? undefined,
    q: searchDebounced || undefined,
    voided: status === "voided" ? true : status === "approved" ? false : undefined,
    limit: PAGE,
  });

  const reload = async () => {
    const gen = ++reloadGen.current;
    setLoading(true);
    try {
      setLoadError("");
      const list = await orgRecords({ ...listParams(), offset: 0 });
      if (gen !== reloadGen.current) return;
      setRows(list);
      setHasMore(hasMorePage(list.length, PAGE));
    } catch (e) {
      if (gen !== reloadGen.current) return;
      // Retain previous rows/hasMore on refresh failure (stale-data soft-fail).
      setLoadError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === reloadGen.current) setLoading(false);
    }
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore || loading) return;
    const gen = reloadGen.current;
    setLoadingMore(true);
    try {
      const more = await orgRecords({ ...listParams(), offset: rows.length });
      if (gen !== reloadGen.current) return;
      setRows((prev) => mergeById(prev, more));
      setHasMore(hasMorePage(more.length, PAGE));
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setLoadError(e instanceof Error ? e.message : "Load more failed");
    } finally {
      if (gen === reloadGen.current) setLoadingMore(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [status, kind, purpose, memberId, searchDebounced]);

  useEffect(() => onResumeRefresh(() => {
    void loadMembers();
    void reload();
  }), []);

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Org ledger</Text>
      <Field
        value={search}
        onChangeText={setSearch}
        placeholder="Search category, place, bike, comment…"
        autoCapitalize="none"
        maxLength={80}
      />
      {(!!status || !!kind || !!purpose || memberId != null || !!search) && (
        <Btn
          title="Clear filters"
          variant="ghost"
          onPress={() => {
            setStatus("");
            setKind("");
            setPurpose("");
            setMemberId(null);
            setSearch("");
          }}
        />
      )}
      <View style={styles.kinds}>
        {(["", "pending", "approved", "rejected", "voided"] as const).map((s) => (
          <Chip key={s || "all"} label={s || "all"} on={status === s} onPress={() => setStatus(s)} />
        ))}
      </View>
      <View style={styles.kinds}>
        {(["", "expense", "fuel", "income"] as const).map((k) => (
          <Chip key={k || "any"} label={k || "any"} on={kind === k} onPress={() => setKind(k)} />
        ))}
      </View>
      <View style={styles.kinds}>
        {(["", "Rental", "Lesson", "Office", "Other"] as const).map((p) => (
          <Chip
            key={p || "any-purpose"}
            label={p || "any purpose"}
            on={purpose === p}
            onPress={() => setPurpose(p)}
          />
        ))}
      </View>
      {!!membersError && (
        <>
          <Sub>Teammate filter unavailable — {membersError}</Sub>
          <Btn title="Retry teammates" variant="ghost" onPress={loadMembers} />
        </>
      )}
      {members.length > 0 && (
        <View style={styles.kinds}>
          <Chip label="anyone" on={memberId == null} onPress={() => setMemberId(null)} />
          {members.map((m) => (
            <Chip
              key={m.id}
              label={m.full_name.split(" ")[0] || m.full_name}
              on={memberId === m.id}
              onPress={() => setMemberId(m.id)}
            />
          ))}
        </View>
      )}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            tintColor={colors.accent}
            onRefresh={async () => {
              setRefreshing(true);
              await reload();
              setRefreshing(false);
            }}
          />
        }
        ListEmptyComponent={
          <Sub>
            {loading
              ? "Loading…"
              : loadError
                ? `Could not load — ${loadError}`
                : status === "voided"
                  ? "No voided records"
                  : status
                    ? `No ${status} records`
                    : "No records"}
          </Sub>
        }
        ListFooterComponent={
          hasMore ? (
            <Btn
              title={loadingMore ? "…" : "Load more"}
              variant="ghost"
              disabled={loadingMore}
              onPress={() => void loadMore()}
            />
          ) : null
        }
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => onRecord(item.id)}>
            <Text style={styles.rowTitle}>
              {item.kind} ·{" "}
              <Text style={{ color: statusColor(item.status, !!item.is_voided) }}>
                {item.is_voided ? "voided" : item.status}
              </Text>
              {" · "}
              {formatMoney(item.amount, item.currency)}
            </Text>
            <Text style={styles.rowMeta}>
              {item.created_by_name || "—"} · {item.purpose || "—"} · {item.category || "—"} ·{" "}
              {formatWhen(item.created_at)}
              {item.is_in_closed_cycle ? " · settled period" : ""}
            </Text>
          </Pressable>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
