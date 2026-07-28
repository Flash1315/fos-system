import React, { useEffect, useRef, useState } from "react";
import { Alert, FlatList, RefreshControl, Text, StyleSheet, View } from "react-native";
import { listMembers, listMyPayouts, listOrgPayouts, makeIdempotencyKey, voidPayout, type User } from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Chip, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen } from "../format";
import { colors } from "../theme";

type PayoutRow = {
  id: number;
  user_id: number;
  user_name: string;
  kind: string;
  amount: number;
  currency: string;
  payment_method: string;
  note: string;
  overpayment?: number;
  balance_after?: number;
  is_voided?: boolean;
  void_note?: string;
  can_void?: boolean;
  void_blocked_reason?: string | null;
  created_at: string;
};

export function PayoutHistoryScreen({
  user,
  onBack,
}: {
  user: User;
  onBack: () => void;
}) {
  const isManager = user.role === "owner" || user.role === "manager";
  const [scope, setScope] = useState<"mine" | "org">(isManager ? "org" : "mine");
  const [voidFilter, setVoidFilter] = useState<"active" | "voided" | "all">("active");
  const [kindFilter, setKindFilter] = useState<"" | "expense_payout" | "income_handover">("");
  const [userFilter, setUserFilter] = useState<number | null>(null);
  const [members, setMembers] = useState<User[]>([]);
  const [rows, setRows] = useState<PayoutRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [voidId, setVoidId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [membersError, setMembersError] = useState("");
  const reloadGen = useRef(0);
  const voidIdemRef = useRef<string | null>(null);
  const voidSlotRef = useRef<number | null>(null);
  const PAGE = 40;

  const loadMembers = async () => {
    if (!isManager) return;
    try {
      setMembersError("");
      setMembers(await listMembers());
    } catch (e) {
      setMembers([]);
      setMembersError(e instanceof Error ? e.message : "Failed to load teammates");
    }
  };

  useEffect(() => {
    void loadMembers();
  }, [isManager]);

  const reload = async () => {
    const gen = ++reloadGen.current;
    setLoading(true);
    try {
      setLoadError("");
      const voided =
        voidFilter === "voided" ? true : voidFilter === "active" ? false : undefined;
      const data =
        scope === "org" && isManager
          ? await listOrgPayouts({
              voided,
              kind: kindFilter || undefined,
              user_id: userFilter ?? undefined,
              limit: PAGE,
              offset: 0,
            })
          : await listMyPayouts({
              voided,
              kind: kindFilter || undefined,
              limit: PAGE,
              offset: 0,
            });
      if (gen !== reloadGen.current) return;
      setRows(data);
      setHasMore(data.length >= PAGE);
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setRows([]);
      setHasMore(false);
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === reloadGen.current) setLoading(false);
    }
  };

  const loadMore = async () => {
    if (loadingMore || !hasMore || loading) return;
    const gen = reloadGen.current;
    setLoadingMore(true);
    try {
      const voided =
        voidFilter === "voided" ? true : voidFilter === "active" ? false : undefined;
      const more =
        scope === "org" && isManager
          ? await listOrgPayouts({
              voided,
              kind: kindFilter || undefined,
              user_id: userFilter ?? undefined,
              limit: PAGE,
              offset: rows.length,
            })
          : await listMyPayouts({
              voided,
              kind: kindFilter || undefined,
              limit: PAGE,
              offset: rows.length,
            });
      if (gen !== reloadGen.current) return;
      setRows((prev) => [...prev, ...more]);
      setHasMore(more.length >= PAGE);
    } catch (e) {
      if (gen !== reloadGen.current) return;
      Alert.alert("Fos", e instanceof Error ? e.message : "Load more failed");
    } finally {
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [scope, voidFilter, kindFilter, userFilter]);

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Payout history</Text>
      {isManager && (
        <View style={styles.kinds}>
          <Chip label="Org" on={scope === "org"} onPress={() => setScope("org")} />
          <Chip label="Mine" on={scope === "mine"} onPress={() => setScope("mine")} />
        </View>
      )}
      <View style={styles.kinds}>
        <Chip label="Active" on={voidFilter === "active"} onPress={() => setVoidFilter("active")} />
        <Chip label="Voided" on={voidFilter === "voided"} onPress={() => setVoidFilter("voided")} />
        <Chip label="All" on={voidFilter === "all"} onPress={() => setVoidFilter("all")} />
      </View>
      <View style={styles.kinds}>
        <Chip label="Any kind" on={kindFilter === ""} onPress={() => setKindFilter("")} />
        <Chip
          label="Reimbursement"
          on={kindFilter === "expense_payout"}
          onPress={() => setKindFilter("expense_payout")}
        />
        <Chip
          label="Handover"
          on={kindFilter === "income_handover"}
          onPress={() => setKindFilter("income_handover")}
        />
      </View>
      {isManager && scope === "org" && membersError ? (
        <>
          <Sub>Teammate filter unavailable — {membersError}</Sub>
          <Btn title="Retry teammates" variant="ghost" onPress={loadMembers} />
        </>
      ) : null}
      {isManager && scope === "org" && members.length > 0 && (
        <View style={styles.kinds}>
          <Chip label="Anyone" on={userFilter == null} onPress={() => setUserFilter(null)} />
          {members.map((m) => (
            <Chip
              key={m.id}
              label={m.full_name.split(" ")[0] || m.full_name}
              on={userFilter === m.id}
              onPress={() => setUserFilter(m.id)}
            />
          ))}
        </View>
      )}
      {(voidFilter !== "active" || !!kindFilter || userFilter != null) && (
        <Btn
          title="Clear filters"
          variant="ghost"
          onPress={() => {
            setVoidFilter("active");
            setKindFilter("");
            setUserFilter(null);
          }}
        />
      )}
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ paddingTop: 8, paddingBottom: 40 }}
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
              ? "Loading..."
              : loadError
                ? `Could not load — ${loadError}`
                : voidFilter === "voided"
                  ? "No voided settlements"
                  : voidFilter === "active"
                    ? "No active settlements"
                    : "No settlements yet"}
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
          <View style={styles.row}>
            <Text style={styles.rowTitle}>
              {item.kind === "expense_payout" ? "Expense reimbursement" : "Cash handover"}
              {" · "}
              {formatMoney(item.amount, item.currency)}
              {item.is_voided ? " · voided" : ""}
            </Text>
            <Text style={styles.rowMeta}>
              {item.user_name} · {item.payment_method} · {formatWhen(item.created_at)}
              {item.balance_after != null
                ? ` · left ${formatMoney(item.balance_after, item.currency)}`
                : ""}
              {item.overpayment != null && item.overpayment > 0
                ? ` · overpay ${formatMoney(item.overpayment, item.currency)}`
                : ""}
              {item.note ? ` · ${item.note}` : ""}
              {item.void_note ? ` · void: ${item.void_note}` : ""}
            </Text>
            {isManager && !!item.can_void && (
              <Btn
                title="Void"
                variant="ghost"
                disabled={busy}
                onPress={() => setVoidId(item.id)}
              />
            )}
            {isManager &&
              !item.is_voided &&
              !item.can_void &&
              !!item.void_blocked_reason && (
                <Text style={styles.rowMeta}>{item.void_blocked_reason}</Text>
              )}
          </View>
        )}
      />
      <NoteModal
        visible={voidId != null}
        title="Void settlement"
        label="Reason (required). Linked settlement request may reopen or cancel."
        required
        confirmTitle="Void"
        confirmVariant="danger"
        onCancel={() => setVoidId(null)}
        onSubmit={async (note) => {
          const id = voidId;
          setVoidId(null);
          if (id == null) return;
          if (voidSlotRef.current !== id) {
            voidSlotRef.current = id;
            voidIdemRef.current = null;
          }
          if (!voidIdemRef.current) voidIdemRef.current = makeIdempotencyKey("pvoid");
          setBusy(true);
          try {
            await voidPayout(id, note, { idempotencyKey: voidIdemRef.current });
            voidIdemRef.current = null;
            voidSlotRef.current = null;
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setBusy(false);
          }
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: {
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  rowTitle: { color: colors.text, fontWeight: "600" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
