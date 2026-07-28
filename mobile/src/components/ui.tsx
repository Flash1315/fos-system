import React from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
} from "react-native";
import { StatusBar } from "expo-status-bar";
import { colors, spacing } from "../theme";

export function Screen({
  children,
  scroll,
  refreshing,
  onRefresh,
}: {
  children: React.ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
}) {
  const body = scroll ? (
    <ScrollView
      contentContainerStyle={styles.scroll}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        onRefresh ? (
          <RefreshControl
            refreshing={!!refreshing}
            onRefresh={onRefresh}
            tintColor={colors.accent}
            colors={[colors.accent]}
          />
        ) : undefined
      }
    >
      {children}
    </ScrollView>
  ) : (
    children
  );
  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        {body}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export function Brand({ small }: { small?: boolean }) {
  return <Text style={small ? styles.brandSmall : styles.brand}>Fos</Text>;
}

export function Sub({ children }: { children: React.ReactNode }) {
  return <Text style={styles.sub}>{children}</Text>;
}

export function Label({ children }: { children: React.ReactNode }) {
  return <Text style={styles.label}>{children}</Text>;
}

export function Field(props: TextInputProps) {
  return (
    <TextInput
      placeholderTextColor="#5A7A6A"
      {...props}
      style={[styles.input, props.style]}
    />
  );
}

export function Btn({
  title,
  onPress,
  disabled,
  variant = "primary",
  style,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  style?: ViewStyle;
}) {
  const bg =
    variant === "secondary"
      ? styles.btnSecondary
      : variant === "danger"
        ? styles.btnDanger
        : variant === "ghost"
          ? styles.btnGhost
          : null;
  return (
    <Pressable
      style={[styles.btn, bg, disabled && styles.btnDisabled, style]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text style={variant === "ghost" ? styles.btnGhostText : styles.btnText}>{title}</Text>
    </Pressable>
  );
}

export function Chip({
  label,
  on,
  onPress,
}: {
  label: string;
  on?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable style={[styles.chip, on && styles.chipOn]} onPress={onPress}>
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

export function Card({ children }: { children: React.ReactNode }) {
  return <View style={styles.card}>{children}</View>;
}

export function Row({ children }: { children: React.ReactNode }) {
  return <View style={styles.rowBtns}>{children}</View>;
}

export function TopBar({
  onBack,
  onCancel,
  title,
  right,
}: {
  onBack?: () => void;
  onCancel?: () => void;
  title?: string;
  right?: React.ReactNode;
}) {
  return (
    <View style={styles.topRow}>
      {onBack ? (
        <Pressable onPress={onBack}><Text style={styles.linkLeft}>← Back</Text></Pressable>
      ) : (
        <Text style={styles.brandSmall}>{title || "Fos"}</Text>
      )}
      {right}
      {onCancel ? (
        <Pressable onPress={onCancel}><Text style={styles.link}>Cancel</Text></Pressable>
      ) : null}
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.accent} />
      <StatusBar style="light" />
    </View>
  );
}

export function LinkText({ children, onPress }: { children: React.ReactNode; onPress: () => void }) {
  return (
    <Pressable onPress={onPress}>
      <Text style={styles.link}>{children}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg, padding: spacing.lg },
  scroll: { paddingBottom: 48 },
  center: { flex: 1, backgroundColor: colors.bg, alignItems: "center", justifyContent: "center" },
  brand: { color: colors.text, fontSize: 42, fontWeight: "700", marginTop: 24 },
  brandSmall: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  sub: { color: colors.muted, marginBottom: 14 },
  card: { backgroundColor: colors.card, borderRadius: 16, padding: spacing.md, marginBottom: spacing.md },
  label: { color: colors.muted, marginBottom: 6, marginTop: 8 },
  input: {
    backgroundColor: colors.bg,
    color: colors.text,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: "center",
    marginTop: 12,
    flex: 1,
  },
  btnSecondary: { backgroundColor: colors.accentDark },
  btnDanger: { backgroundColor: colors.danger },
  btnGhost: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: colors.border,
    flex: 0,
  },
  btnDisabled: { opacity: 0.5 },
  btnText: { color: colors.ink, fontWeight: "700" },
  btnGhostText: { color: colors.link, fontWeight: "700" },
  link: { color: colors.link, marginTop: 14, textAlign: "center" },
  linkLeft: { color: colors.link, marginTop: 14, textAlign: "left" },
  topRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  rowBtns: { flexDirection: "row", gap: 10, marginBottom: 8, flexWrap: "wrap" },
  chip: { paddingVertical: 8, paddingHorizontal: 12, borderRadius: 20, backgroundColor: colors.card },
  chipOn: { backgroundColor: colors.accent },
  chipText: { color: colors.text, fontWeight: "600", textTransform: "capitalize" },
});
