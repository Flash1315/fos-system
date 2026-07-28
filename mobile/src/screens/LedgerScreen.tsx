import React, { useEffect, useState } from "react";
import { Alert, FlatList, Pressable, RefreshControl, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { listMembers, orgRecords, type MoneyRecord, type User } from "../api";
import { Chip, Field, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
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
  const [status, setStatus] = useState<"" | "pending" | "approved" | "rejected">("");
  const [kind, setKind] = useState<"" | "expense" | "fuel" | "income">("");
  const [purpose, setPurpose] = useState("");
  const [memberId, setMemberId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        setMembers(await listMembers());
      } catch {
        /* ignore — ledger still works without member chips */
      }
    })();
  }, []);

  const reload = async () => {
    try {
      setRows(
        await orgRecords({
          status: status || undefined,
          kind: kind || undefined,
          purpose: purpose || undefined,
          created_by: memberId ?? undefined,
          q: search.trim() || undefined,
        }),
      );
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);
  useEffect(() => {
    void reload();
  }, [status, kind, purpose, memberId, search]);

  return (
    <Screen>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Org ledger</Text>
      <Field
        value={search}
        onChangeText={setSearch}
        placeholder="Search category, place, bike, comment…"
        autoCapitalize="none"
      />
      <View style={styles.kinds}>
        {(["", "pending", "approved", "rejected"] as const).map((s) => (
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
        ListEmptyComponent={<Sub>No records</Sub>}
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
