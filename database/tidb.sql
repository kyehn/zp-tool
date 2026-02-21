SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for job
-- ----------------------------
DROP TABLE IF EXISTS `job`;
CREATE TABLE `job` (
  `id` varchar(512) NOT NULL,
  `acceptable` tinyint(1) DEFAULT NULL,
  `contacted` tinyint(1) DEFAULT NULL,
  `last_inspection_time` datetime DEFAULT NULL,
  `detail` json DEFAULT NULL,
  `user_id` varchar(512) GENERATED ALWAYS AS (json_unquote(json_extract(`detail`, _utf8mb4'$.jobInfo.encryptUserId'))) VIRTUAL,
  `brand_id` varchar(512) GENERATED ALWAYS AS (json_unquote(json_extract(`detail`, _utf8mb4'$.brandComInfo.encryptBrandId'))) VIRTUAL,
  PRIMARY KEY (`id`) /*T![clustered_index] CLUSTERED */,
  KEY `idx_user_id` (`user_id`),
  KEY `idx_brand_id` (`brand_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ----------------------------
-- Table structure for mask_company
-- ----------------------------
DROP TABLE IF EXISTS `mask_company`;
CREATE TABLE `mask_company` (
  `com_id` bigint(20) NOT NULL,
  `encrypt_id` varchar(512) DEFAULT NULL,
  `com_name` varchar(512) DEFAULT NULL,
  `link_com_num` tinyint(4) DEFAULT '0',
  `encrypt_com_id` varchar(512) DEFAULT NULL,
  PRIMARY KEY (`com_id`) /*T![clustered_index] CLUSTERED */
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- ----------------------------
-- Table structure for user_black
-- ----------------------------
DROP TABLE IF EXISTS `user_black`;
CREATE TABLE `user_black` (
  `user_id` bigint(20) NOT NULL,
  `name` varchar(512) DEFAULT NULL,
  `avatar` varchar(512) DEFAULT NULL,
  `security_id` varchar(512) DEFAULT NULL,
  `info` varchar(512) DEFAULT NULL,
  `user_source` tinyint(1) DEFAULT '0',
  PRIMARY KEY (`user_id`) /*T![clustered_index] CLUSTERED */
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

SET FOREIGN_KEY_CHECKS = 1;
