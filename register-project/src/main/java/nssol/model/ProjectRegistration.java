package nssol.model;

import java.math.BigDecimal;

/**
 * NSSOL Projects record — fields documented in LTM D05 (Data Model) ¶48–76.
 * Subset of the 27 documented fields, sufficient for the documented form.
 * Nullable fields follow the documented schema nullability.
 */
public class ProjectRegistration {

    private Integer projectId;
    private String projectName;
    private Boolean isActive;
    private String status;
    private java.time.LocalDate startDate;
    private java.time.LocalDate endDate;
    private java.time.LocalDate orderDate;
    private java.time.LocalDate statusChanged;
    private BigDecimal orderAmountMillionYen;
    private BigDecimal expectedOrderAmount;
    private String orderFiscalYear;
    private String probability;
    private String projectCategory;
    private String client;
    private String inquirySource;
    private String constructionSite;
    private String buildingUsage;
    private String headOffice;
    private String branchOffice;
    private String targetOrganization;
    private String responsibleDepartment;
    private String siteRepresentative;
    private String specialNotes;
    private String primeContractor;
    private Integer completedProjects;
    private Integer plannedHeadCount;
    private Integer actualHeadcount;

    public Integer getProjectId() { return projectId; }
    public void setProjectId(Integer projectId) { this.projectId = projectId; }
    public String getProjectName() { return projectName; }
    public void setProjectName(String projectName) { this.projectName = projectName; }
    public Boolean isIsActive() { return isActive; }
    public void setIsActive(Boolean isActive) { this.isActive = isActive; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public java.time.LocalDate getStartDate() { return startDate; }
    public void setStartDate(java.time.LocalDate startDate) { this.startDate = startDate; }
    public java.time.LocalDate getEndDate() { return endDate; }
    public void setEndDate(java.time.LocalDate endDate) { this.endDate = endDate; }
    public java.time.LocalDate getOrderDate() { return orderDate; }
    public void setOrderDate(java.time.LocalDate orderDate) { this.orderDate = orderDate; }
    public java.time.LocalDate getStatusChanged() { return statusChanged; }
    public void setStatusChanged(java.time.LocalDate statusChanged) { this.statusChanged = statusChanged; }
    public BigDecimal getOrderAmountMillionYen() { return orderAmountMillionYen; }
    public void setOrderAmountMillionYen(BigDecimal v) { this.orderAmountMillionYen = v; }
    public BigDecimal getExpectedOrderAmount() { return expectedOrderAmount; }
    public void setExpectedOrderAmount(BigDecimal v) { this.expectedOrderAmount = v; }
    public String getOrderFiscalYear() { return orderFiscalYear; }
    public void setOrderFiscalYear(String v) { this.orderFiscalYear = v; }
    public String getProbability() { return probability; }
    public void setProbability(String v) { this.probability = v; }
    public String getProjectCategory() { return projectCategory; }
    public void setProjectCategory(String v) { this.projectCategory = v; }
    public String getClient() { return client; }
    public void setClient(String v) { this.client = v; }
    public String getInquirySource() { return inquirySource; }
    public void setInquirySource(String v) { this.inquirySource = v; }
    public String getConstructionSite() { return constructionSite; }
    public void setConstructionSite(String v) { this.constructionSite = v; }
    public String getBuildingUsage() { return buildingUsage; }
    public void setBuildingUsage(String v) { this.buildingUsage = v; }
    public String getHeadOffice() { return headOffice; }
    public void setHeadOffice(String v) { this.headOffice = v; }
    public String getBranchOffice() { return branchOffice; }
    public void setBranchOffice(String v) { this.branchOffice = v; }
    public String getTargetOrganization() { return targetOrganization; }
    public void setTargetOrganization(String v) { this.targetOrganization = v; }
    public String getResponsibleDepartment() { return responsibleDepartment; }
    public void setResponsibleDepartment(String v) { this.responsibleDepartment = v; }
    public String getSiteRepresentative() { return siteRepresentative; }
    public void setSiteRepresentative(String v) { this.siteRepresentative = v; }
    public String getSpecialNotes() { return specialNotes; }
    public void setSpecialNotes(String v) { this.specialNotes = v; }
    public String getPrimeContractor() { return primeContractor; }
    public void setPrimeContractor(String v) { this.primeContractor = v; }
    public Integer getCompletedProjects() { return completedProjects; }
    public void setCompletedProjects(Integer v) { this.completedProjects = v; }
    public Integer getPlannedHeadCount() { return plannedHeadCount; }
    public void setPlannedHeadCount(Integer v) { this.plannedHeadCount = v; }
    public Integer getActualHeadcount() { return actualHeadcount; }
    public void setActualHeadcount(Integer v) { this.actualHeadcount = v; }
}
