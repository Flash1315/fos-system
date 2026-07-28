import React, { useEffect, useState } from "react";
import { Alert, FlatList, Pressable, RefreshControl, Text, View, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { listMySettlementRequests, listSettlementRequests, myBalance, myOrg, myRecords, pendingRecords, requestSettlement, type MoneyRecord, type User } from "../api";
import { Brand, Btn, Card, Chip, Field, Label, LinkText, Row, Screen, Sub } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { colors } from "../theme";

export function HomeScreen({
  user,
  onCreate,
  onApprove,
  onInvite,
  onTeam,
  onReports,
  onMyReport,
  onLedger,
  onTransfer,
  onPayout,
  onPayoutHistory,
  onBalances,
  onAccount,
  onRecord,
  onLogout,
}: {
  user: User | null;
  onCreate: () => void;
  onApprove: () => void;
  onInvite: () => void;
  onTeam: () => void;
  onReports: () => void;
  onMyReport: () => void;
  onLedger: () => void;
  onTransfer: () => void;
  onPayout: () => void;
  onPayoutHistory: () => void;
  onBalances: () => void;
  onAccount: () => void;
  onRecord: (id: number) => void;
  onLogout: () => void;
}) {
  const [balance, setBalance] = useState("—");
  const [spendings, setSpendings] = useState("—");
  const [cycleHint, setCycleHint] = useState("");
  const [availableSpend, setAvailableSpend] = useState(0);
  const [availableCash, setAvailableCash] = useState(0);
  const [currencyCode, setCurrencyCode] = useState("IDR");
  const [requestBusy, setRequestBusy] = useState(false);
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [pendingCount, setPendingCount] = useState(0);
  const [settlementCount, setSettlementCount] = useState(0);
  const [rows, setRows] = useState<MoneyRecord[]>([]);
  const [status, setStatus] = useState<"" | "pending" | "approved" | "rejected" | "voided">("");
  const [purpose, setPurpose] = useState("");
  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setSearchDebounced(search.trim()), 350);
    return () => clearTimeout(t);
  }, [search]);

  const reload = async () => {
    try {
      setLoadError("");
      const [b, org, list] = await Promise.all([
        myBalance(),
        myOrg(),
        myRecords({
          status: status && status !== "voided" ? status : undefined,
          purpose: purpose || undefined,
          q: searchDebounced || undefined,
          voided: status === "voided" ? true : status === "approved" ? false : undefined,
        }),
      ]);
      setBalance(formatMoney(b.cash_on_hand, b.currency));
      setSpendings(formatMoney(b.spendings ?? 0, b.currency));
      setAvailableSpend(b.available_spendings ?? b.spendings ?? 0);
      setAvailableCash(b.available_cash ?? b.cash_on_hand ?? 0);
      setCurrencyCode(b.currency);
      const hints: string[] = [];
      const reservedSpend = b.reserved_spendings || 0;
      const reservedCash = b.reserved_cash || 0;
      if (reservedSpend > 0 || reservedCash > 0) {
        if (reservedSpend > 0) {
          hints.push(
            `Available spendings ${formatMoney(b.available_spendings ?? b.spendings, b.currency)} (reserved ${formatMoney(reservedSpend, b.currency)})`,
          );
        }
        if (reservedCash > 0) {
          hints.push(
            `Available cash ${formatMoney(b.available_cash ?? b.cash_on_hand, b.currency)} (reserved ${formatMoney(reservedCash, b.currency)})`,
          );
        }
      }
      if (b.last_expense_payout_at || b.last_income_handover_at) {
        hints.push(
          `Since payout ${formatWhen(b.last_expense_payout_at)} · handover ${formatWhen(b.last_income_handover_at)}`,
        );
      }
      setCycleHint(hints.join("\n"));
      setOrgName(org.name);
      setOrgSlug(org.slug);
      if (user?.role === "owner" || user?.role === "manager") {
        try {
          const pend = await pendingRecords();
          setPendingCount(pend.length);
        } catch {
          setPendingCount(b.pending_count);
        }
        try {
          const reqs = await listSettlementRequests();
          setSettlementCount(reqs.length);
        } catch {
          setSettlementCount(0);
        }
      } else {
        setPendingCount(b.pending_count);
        try {
          const mine = await listMySettlementRequests();
          setSettlementCount(mine.filter((r) => r.status === "pending").length);
        } catch {
          setSettlementCount(0);
        }
      }
      setRows(list);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Load failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Load failed");
    } finally {
      setLoading(false);
    }
  };

  useFocusEffect(reload);
  useEffect(() => {
    void reload();
  }, [status, purpose, searchDebounced]);

  const isManager = user?.role === "owner" || user?.role === "manager";

  const quickRequest = async (kind: "expense_payout" | "income_handover") => {
    const amount = kind === "expense_payout" ? availableSpend : availableCash;
    if (amount <= 0) {
      Alert.alert("Fos", "Nothing available to request");
      return;
    }
    const label =
      kind === "expense_payout"
        ? `Request expense reimbursement ${formatMoney(amount, currencyCode)}?`
        : `Request cash handover ${formatMoney(amount, currencyCode)}?`;
    Alert.alert("Fos", label, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Send",
        onPress: async () => {
          setRequestBusy(true);
          try {
            await requestSettlement({
              kind,
              amount,
              note:
                kind === "expense_payout"
                  ? "quick request from home"
                  : "quick cash handover request",
            });
            Alert.alert("Fos", "Settlement request sent");
            await reload();
          } catch (e) {
            Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
          } finally {
            setRequestBusy(false);
          }
        },
      },
    ]);
  };

  return (
    <Screen>
      <View style={styles.topRow}>
        <View>
          <Brand small />
          <Sub>
            {orgName ? `${orgName}` : ""}
            {orgSlug ? ` · /${orgSlug}` : ""}
            {orgName || orgSlug ? " · " : ""}
            {user?.full_name} · {user?.role}
          </Sub>
        </View>
        <LinkText onPress={onLogout}>Log out</LinkText>
      </View>
      <Card>
        <Label>Cash on hand</Label>
        <Text style={styles.balance}>{balance}</Text>
        <Label>Spendings (my pocket)</Label>
        <Text style={styles.spend}>{spendings}</Text>
        {!!cycleHint && <Sub>{cycleHint}</Sub>}
        {(availableSpend > 0 || availableCash > 0) && (
          <Row>
            {availableSpend > 0 && (
              <Btn
                title={requestBusy ? "…" : `Request reimbursement ${formatMoney(availableSpend, currencyCode)}`}
                variant="ghost"
                disabled={requestBusy}
                onPress={() => quickRequest("expense_payout")}
              />
            )}
            {availableCash > 0 && (
              <Btn
                title={requestBusy ? "…" : `Request handover ${formatMoney(availableCash, currencyCode)}`}
                variant="ghost"
                disabled={requestBusy}
                onPress={() => quickRequest("income_handover")}
              />
            )}
          </Row>
        )}
      </Card>
      <Row>
        <Btn title="New record" onPress={onCreate} />
        {isManager && (
          <Btn
            title={pendingCount > 0 ? `Approvals (${pendingCount})` : "Approvals"}
            onPress={onApprove}
            variant="secondary"
          />
        )}
      </Row>
      <Row>
        <Btn title="Transfer" onPress={onTransfer} variant="ghost" />
        <Btn title="My stats" onPress={onMyReport} variant="ghost" />
        <Btn
          title={settlementCount > 0 ? `Account (${settlementCount})` : "Account"}
          onPress={onAccount}
          variant="ghost"
        />
      </Row>
      {isManager && (
        <Row>
          <Btn title="Invite" onPress={onInvite} variant="ghost" />
          <Btn title="Team" onPress={onTeam} variant="ghost" />
          <Btn title="Reports" onPress={onReports} variant="ghost" />
        </Row>
      )}
      {isManager && (
        <Row>
          <Btn title="Ledger" onPress={onLedger} variant="ghost" />
          <Btn title="Settlements" onPress={onPayout} variant="ghost" />
          <Btn title="Balances" onPress={onBalances} variant="ghost" />
        </Row>
      )}
      <Btn title="Payout history" onPress={onPayoutHistory} variant="ghost" />
      <Field
        value={search}
        onChangeText={setSearch}
        placeholder="Search my records…"
        autoCapitalize="none"
      />
      <View style={styles.filters}>
        {(["", "pending", "approved", "rejected", "voided"] as const).map((s) => (
          <Chip key={s || "all"} label={s || "all"} on={status === s} onPress={() => setStatus(s)} />
        ))}
      </View>
      <View style={styles.filters}>
        {(["", "Rental", "Lesson", "Office", "Other"] as const).map((p) => (
          <Chip
            key={p || "any-p"}
            label={p || "any purpose"}
            on={purpose === p}
            onPress={() => setPurpose(p)}
          />
        ))}
      </View>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.id)}
        contentContainerStyle={{ paddingBottom: 40 }}
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
        ListHeaderComponent={<Text style={styles.section}>My records</Text>}
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
                    : "No records yet"}
          </Sub>
        }
        renderItem={({ item }) => (
          <Pressable style={styles.row} onPress={() => onRecord(item.id)}>
            <Text style={styles.rowTitle}>
              {item.kind} ·{" "}
              <Text style={{ color: statusColor(item.status, !!item.is_voided) }}>
                {item.is_voided ? "voided" : item.status}
              </Text>
            </Text>
            <Text style={styles.rowMeta}>
              {formatMoney(item.amount, item.currency)} · {item.category || "—"}
              {item.purpose ? ` · ${item.purpose}` : ""}
              {item.payment_source === "my_pocket" ? " · my pocket" : ""}
            </Text>
            <Text style={styles.rowMeta}>{formatWhen(item.created_at)}</Text>
          </Pressable>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  balance: { color: colors.text, fontSize: 24, fontWeight: "700" },
  spend: { color: colors.warning, fontSize: 18, fontWeight: "700", marginTop: 4 },
  section: { color: colors.text, fontWeight: "600", marginBottom: 8, marginTop: 8 },
  filters: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  row: { backgroundColor: colors.card, borderRadius: 12, padding: 12, marginBottom: 8 },
  rowTitle: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
  rowMeta: { color: colors.muted, marginTop: 4 },
});
