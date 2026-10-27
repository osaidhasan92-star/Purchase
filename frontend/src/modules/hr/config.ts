export type Resource =
  | "employees"
  | "manpower"
  | "candidates"
  | "attendance"
  | "leaves"
  | "payroll"
  | "separations";
export interface RecordData {
  id: string | number;
  version: string;
  status: string;
  actions: string[];
  [key: string]: unknown;
}
export interface Field {
  key: string;
  label: string;
  type?: string;
  options?: string[];
  required?: boolean;
}
const field = (
  key: string,
  label: string,
  type = "text",
  required = true,
  options?: string[],
): Field => ({ key, label, type, required, options });
export const configs: Record<
  Resource,
  {
    title: string;
    module: string;
    view: string;
    fields: Field[];
    columns: string[];
  }
> = {
  employees: {
    title: "Employees",
    module: "hr_employees",
    view: "hr-employees",
    columns: [
      "employeeId",
      "name",
      "department",
      "designation",
      "salary",
      "status",
    ],
    fields: [
      field("employeeId", "Employee ID"),
      field("name", "Full name"),
      field("department", "Department"),
      field("designation", "Designation"),
      field("manager", "Reporting manager", "text", false),
      field("joiningDate", "Joining date", "date"),
      field("salary", "Monthly basic salary (PKR)", "number"),
      field("email", "Contact email", "email", false),
      field("candidateId", "Candidate", "candidate", false),
    ],
  },
  manpower: {
    title: "Manpower Requests",
    module: "hr_manpower",
    view: "hr-manpower",
    columns: ["department", "position", "count", "status"],
    fields: [
      field("department", "Department"),
      field("position", "Position"),
      field("requestType", "Request type", "select", true, [
        "New Position",
        "Replacement",
      ]),
      field("count", "Headcount", "number"),
      field("reason", "Reason"),
      field("requestedBy", "Requested by"),
    ],
  },
  candidates: {
    title: "Recruitment",
    module: "hr_recruitment",
    view: "hr-recruitment",
    columns: ["name", "position", "contact", "stage"],
    fields: [
      field("name", "Candidate name"),
      field("position", "Position"),
      field("contact", "Email / phone"),
      field("manpowerId", "Manpower request", "manpower", false),
    ],
  },
  attendance: {
    title: "Attendance",
    module: "hr_attendance",
    view: "hr-attendance",
    columns: ["employee", "date", "attendanceStatus"],
    fields: [
      field("employeeKey", "Employee", "employee"),
      field("date", "Date", "date"),
      field("attendanceStatus", "Attendance status", "select", true, [
        "Present",
        "Absent",
        "Late",
        "Half Day",
        "Work From Home",
      ]),
    ],
  },
  leaves: {
    title: "Leave Requests",
    module: "hr_leave",
    view: "hr-leave",
    columns: ["employee", "leaveType", "from", "to", "days", "status"],
    fields: [
      field("employeeKey", "Employee", "employee"),
      field("leaveType", "Leave type", "select", true, [
        "Annual",
        "Sick",
        "Casual",
        "Unpaid",
      ]),
      field("from", "From", "date"),
      field("to", "To", "date"),
      field("reason", "Reason"),
    ],
  },
  payroll: {
    title: "Payroll",
    module: "hr_payroll",
    view: "hr-payroll",
    columns: [
      "employee",
      "month",
      "basic",
      "allowances",
      "deductions",
      "netPay",
      "status",
    ],
    fields: [
      field("employeeKey", "Employee", "employee"),
      field("month", "Payroll month", "month"),
      field("basic", "Basic salary (PKR)", "number"),
      field("allowances", "Allowances (PKR)", "number"),
      field("deductions", "Deductions (PKR)", "number"),
    ],
  },
  separations: {
    title: "Employee Separation",
    module: "hr_separation",
    view: "hr-separation",
    columns: ["employee", "lastWorkingDate", "finalSettlement", "status"],
    fields: [
      field("employeeKey", "Employee", "employee"),
      field("lastWorkingDate", "Last working date", "date"),
      field("reason", "Reason"),
      field("finalSettlement", "Final settlement estimate (PKR)", "number"),
    ],
  },
};
export const labels: Record<string, string> = {
  employeeId: "Employee ID",
  name: "Name",
  department: "Department",
  designation: "Designation",
  salary: "Basic salary (PKR)",
  count: "Headcount",
  position: "Position",
  contact: "Contact",
  stage: "Stage",
  employee: "Employee",
  date: "Date",
  attendanceStatus: "Attendance",
  leaveType: "Leave type",
  from: "From",
  to: "To",
  days: "Days",
  month: "Month",
  basic: "Basic (PKR)",
  allowances: "Allowances (PKR)",
  deductions: "Deductions (PKR)",
  netPay: "Net pay (PKR)",
  status: "Status",
  lastWorkingDate: "Last working date",
  finalSettlement: "Settlement estimate (PKR)",
  approve: "Approve",
  pay: "Record Payment",
  shortlist: "Shortlist",
  interview: "Schedule Interview",
  select: "Select Candidate",
  offer: "Issue Offer",
  reject: "Reject",
  cancel: "Cancel Request",
  complete: "Complete Exit",
  login: "Create Login",
};
export const keyFor = () =>
  "hr-" + Date.now() + "-" + Math.random().toString(36).slice(2);
export const display = (value: unknown) =>
  value === null || value === undefined ? "—" : String(value);
